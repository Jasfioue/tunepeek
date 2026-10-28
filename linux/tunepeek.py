#!/usr/bin/env python3
"""Tunepeek — мини-плеер поверх всех окон: показывает, что играет (YouTube/SoundCloud в браузере, Spotify, VLC... — всё, что говорит MPRIS).
Видна только обложка; на новом треке название выезжает на 5 с. Навести на обложку — раскрыть.
ЛКМ по кнопкам — назад/пауза/вперёд, ЛКМ+тянуть — двигать, тянуть за край — размер, ПКМ — выход. Мимо панели клики проходят насквозь.
Запуск: python3 tunepeek.py   |   проверка: python3 tunepeek.py --selftest
"""
import math, os, sys, threading, urllib.request
import cairo, gi
gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0'); gi.require_version('PangoCairo', '1.0')
gi.require_foreign('cairo')
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib, Pango, PangoCairo

W, H, ART, PAD, MARGIN = 270, 64, 48, 8, 16
CW = ART + 2 * PAD  # ширина свёрнутой панели — только обложка
BTN_Y, BTN_R = 48, 8
BTNS = [('Previous', 10), ('PlayPause', 38), ('Next', 66)]  # x от левого края текста
SHOW_MS, HOVER_OUT_MS = 5000, 1500
BG_ALPHA, ART_ALPHA = 0.6, 0.9
PREFIX = 'org.mpris.MediaPlayer2.'
SCALE_MIN, SCALE_MAX = 0.75, 2.0
EDGE = 6  # px у края панели, за которые хватается ресайз
CURSORS = {'l': 'ew-resize', 'r': 'ew-resize', 't': 'ns-resize', 'b': 'ns-resize'}
SCALE_FILE = os.path.join(GLib.get_user_config_dir(), 'tunepeek-scale')


def pick(players, prev):
    """players: [(name, status)] -> имя для показа. Играющий важнее паузы, прежний — при равенстве."""
    if not players: return None
    rank = {'Playing': 0, 'Paused': 1}
    return min(players, key=lambda p: (rank.get(p[1], 2), p[0] != prev))[0]


def panel_w(k):
    """k 0..1 -> ширина панели; выезд с замедлением в конце."""
    return round(CW + (W - CW) * (1 - (1 - k) ** 3))


def clamp_scale(v):
    return round(min(SCALE_MAX, max(SCALE_MIN, v)), 2)


def resize_scale(s0, length, delta):
    """Край панели длиной length (px, масштаб s0) утянули на delta px -> новый масштаб, край идёт за курсором."""
    return clamp_scale(s0 * (length + delta) / length)


def rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    for cx, cy, a in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        cr.arc(cx, cy, r, math.radians(a), math.radians(a + 90))
    cr.close_path()


class Player(Gtk.Window):
    def __init__(s):
        # POPUP = override-redirect: оконный менеджер не управляет окном, и мы можем держать его над полноэкранными
        super().__init__(type=Gtk.WindowType.POPUP)
        s.set_visual(s.get_screen().get_rgba_visual()); s.set_app_paintable(True)
        try: s.S = clamp_scale(float(open(SCALE_FILE).read()))
        except (OSError, ValueError): s.S = 1.0
        s.set_default_size(W * s.S, H * s.S)
        mon = Gdk.Display.get_default()
        geo = (mon.get_primary_monitor() or mon.get_monitor(0)).get_workarea()  # без панелей XFCE
        s.move(geo.x + geo.width - W * s.S - MARGIN, geo.y + MARGIN)
        s.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        s.proxies, s.cur, s.meta, s.status, s.track = {}, None, {}, '', None
        s.art_url, s.art, s.drag, s.resizing = None, None, None, None
        s.k, s.target, s.anim_id, s.hide_id, s.hover = 0.0, 0.0, None, None, False
        s.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                     | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
)
        s.connect('draw', s.on_draw); s.connect('button-press-event', s.on_press)
        s.connect('button-release-event', s.on_release)
        s.connect('motion-notify-event', s.on_motion)
        s.connect('enter-notify-event', lambda *a: (setattr(s, 'hover', True), s.expand(None)))
        s.connect('leave-notify-event', lambda *a: (setattr(s, 'hover', False), s.expand(HOVER_OUT_MS)))
        s.poll(); GLib.timeout_add(1000, s.poll)

    def proxy(s, name):
        if name not in s.proxies:
            s.proxies[name] = Gio.DBusProxy.new_sync(s.bus, 0, None, name, '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player')
        return s.proxies[name]

    def prop(s, name, key):
        v = s.proxy(name).get_cached_property(key)
        return v.unpack() if v is not None else None

    def poll(s):
        # shortcut: опрос раз в секунду вместо подписки на сигналы D-Bus — проще, задержка ≤1 с
        names = s.bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames',
                                None, GLib.VariantType('(as)'), 0, -1, None).unpack()[0]
        names = [n for n in names if n.startswith(PREFIX)]
        for gone in set(s.proxies) - set(names): del s.proxies[gone]
        s.cur = pick([(n, s.prop(n, 'PlaybackStatus')) for n in names], s.cur)
        # ничего не играет — панель всё равно видна, иначе после запуска кажется, что плеер не открылся
        s.meta, s.status = (s.prop(s.cur, 'Metadata') or {}, s.prop(s.cur, 'PlaybackStatus') or '') if s.cur else ({}, '')
        url = s.meta.get('mpris:artUrl')
        if url != s.art_url:
            s.art_url, s.art = url, None
            if url: threading.Thread(target=s.load_art, args=(url,), daemon=True).start()
        track = (s.cur, s.meta.get('xesam:title'), tuple(s.meta.get('xesam:artist') or []))
        if track != s.track:
            s.track = track; s.expand(SHOW_MS)
        if not s.get_visible(): s.show_all(); s.set_input()
        s.get_window().raise_()  # каждый тик снова наверх — игра могла перекрыть
        s.queue_draw()
        return True

    def expand(s, ms):
        """Раскрыть панель; через ms свернуть (None — держать открытой, пока курсор на ней)."""
        if s.hide_id: GLib.source_remove(s.hide_id); s.hide_id = None
        s.animate(1)
        if ms: s.hide_id = GLib.timeout_add(ms, s.collapse)

    def collapse(s):
        s.hide_id = None
        if not s.hover: s.animate(0)
        return False

    def animate(s, target):
        s.target = target
        if not s.anim_id: s.anim_id = GLib.timeout_add(16, s.step)

    def step(s):
        s.k = min(1, s.k + 0.05) if s.target > s.k else max(0, s.k - 0.05)
        s.set_input(); s.queue_draw()
        if s.k == s.target: s.anim_id = None; return False
        return True

    def set_input(s):
        # клики принимает только видимая панель, остальное окно прозрачно для мыши
        pw = panel_w(s.k)
        if s.get_window(): s.input_shape_combine_region(cairo.Region(cairo.RectangleInt(round((W - pw) * s.S), 0, round(pw * s.S), round(H * s.S))))

    def load_art(s, url):
        try:
            loader = GdkPixbuf.PixbufLoader(); loader.write(urllib.request.urlopen(url, timeout=5).read()); loader.close()
            pb = loader.get_pixbuf()
            side = min(pb.get_width(), pb.get_height())  # обрезаем до квадрата (у YouTube превью 16:9)
            pb = pb.new_subpixbuf((pb.get_width() - side) // 2, (pb.get_height() - side) // 2, side, side)
            pb = pb.scale_simple(ART * 2, ART * 2, GdkPixbuf.InterpType.BILINEAR)  # запас резкости под увеличение
        except Exception:
            return
        GLib.idle_add(lambda: url == s.art_url and (setattr(s, 'art', pb), s.queue_draw()) and False)

    def text(s, cr, x, y, txt, font, alpha):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription(font)); lay.set_text(txt, -1)
        lay.set_width((W - CW - PAD) * Pango.SCALE); lay.set_ellipsize(Pango.EllipsizeMode.END)
        cr.set_source_rgba(0.93, 0.94, 0.96, alpha); cr.move_to(x, y); PangoCairo.show_layout(cr, lay)

    def on_draw(s, w, cr):
        cr.set_operator(0); cr.paint(); cr.set_operator(2)  # CLEAR, потом OVER
        cr.scale(s.S, s.S)  # дальше всё рисуем в «единичных» координатах
        pw = panel_w(s.k); x0 = W - pw
        rrect(cr, x0, 0, pw, H, 12); cr.set_source_rgba(0.13, 0.15, 0.19, BG_ALPHA); cr.fill()
        if pw > CW:
            # текст едет вместе с левым краем и прячется под обложку
            cr.save(); cr.rectangle(x0, 0, pw - CW, H); cr.clip()
            tx, a = x0 + PAD, s.k
            s.text(cr, tx, 5, s.meta.get('xesam:title') or ('Без названия' if s.cur else 'Ничего не играет'), 'Sans Bold 10', a)
            s.text(cr, tx, 22, ', '.join(s.meta.get('xesam:artist') or []), 'Sans 8', 0.65 * a)
            src = s.cur[len(PREFIX):].split('.')[0] if s.cur else ''
            lay = PangoCairo.create_layout(cr); lay.set_font_description(Pango.FontDescription('Sans 7')); lay.set_text(src, -1)
            cr.set_source_rgba(1, 1, 1, 0.35 * a); cr.move_to(tx + W - CW - PAD - lay.get_pixel_size()[0], BTN_Y - 5)
            PangoCairo.show_layout(cr, lay)
            cr.set_source_rgba(0.93, 0.94, 0.96, 0.9 * a)
            for cmd, ox in BTNS if s.cur else []:
                bx = tx + ox
                if cmd == 'PlayPause' and s.status == 'Playing':
                    cr.rectangle(bx - 4, BTN_Y - 5, 3, 10); cr.rectangle(bx + 1, BTN_Y - 5, 3, 10)
                elif cmd == 'PlayPause':
                    cr.move_to(bx - 3, BTN_Y - 6); cr.line_to(bx + 6, BTN_Y); cr.line_to(bx - 3, BTN_Y + 6)
                else:
                    d = 1 if cmd == 'Next' else -1
                    for o in (-4, 1):
                        cr.move_to(bx + d * o, BTN_Y - 4); cr.line_to(bx + d * (o + 5), BTN_Y); cr.line_to(bx + d * o, BTN_Y + 4)
                cr.fill()
            cr.restore()
        ax = W - PAD - ART
        cr.save(); rrect(cr, ax, PAD, ART, ART, 8); cr.clip()
        if s.art:
            cr.translate(ax, PAD); cr.scale(0.5, 0.5)
            Gdk.cairo_set_source_pixbuf(cr, s.art, 0, 0); cr.paint_with_alpha(ART_ALPHA)
        else:
            cr.set_source_rgba(1, 1, 1, 0.08); cr.paint()
            s.text(cr, ax + 16, PAD + 10, '♪', 'Sans 16', 0.5)
        cr.restore()

    def on_press(s, w, e):
        if e.button == 3: Gtk.main_quit(); return
        tx, ex, ey = W - panel_w(s.k) + PAD, e.x / s.S, e.y / s.S
        for cmd, ox in BTNS:
            if s.k > 0.9 and s.cur and (ex - tx - ox) ** 2 + (ey - BTN_Y) ** 2 <= (BTN_R + 4) ** 2:
                s.proxy(s.cur).call(cmd, None, 0, -1, None, None, None)
                GLib.timeout_add(200, lambda: s.poll() and False)
                return
        edge = s.edge_at(e.x, e.y)
        if edge:
            length = (panel_w(s.k) if edge in 'lr' else H) * s.S
            s.resizing = (edge, s.S, e.x_root, e.y_root, *s.get_position(), length)
        else:
            s.drag = (e.x, e.y)

    def on_release(s, w, e):
        if s.resizing:
            try: open(SCALE_FILE, 'w').write(str(s.S))
            except OSError: pass
        s.drag = s.resizing = None

    def edge_at(s, x, y):
        x0, w, h = (W - panel_w(s.k)) * s.S, W * s.S, H * s.S
        return 'l' if x - x0 < EDGE else 'r' if w - x < EDGE else 't' if y < EDGE else 'b' if h - y < EDGE else None

    def on_motion(s, w, e):
        if s.resizing:
            edge, s0, px, py, x0, y0, length = s.resizing
            d = {'l': px - e.x_root, 'r': e.x_root - px, 't': py - e.y_root, 'b': e.y_root - py}[edge]
            s.S = resize_scale(s0, length, d)
            # противоположный край стоит на месте; для верх/низ — правый край, как у всей панели
            x = x0 + (W - panel_w(s.k) if edge == 'r' else W) * (s0 - s.S)
            s.move(round(x), round(y0 + H * (s0 - s.S) if edge == 't' else y0))
            s.resize(round(W * s.S), round(H * s.S)); s.set_input(); s.queue_draw()
        elif s.drag:
            s.move(int(e.x_root - s.drag[0]), int(e.y_root - s.drag[1]))
        else:
            edge = s.edge_at(e.x, e.y)
            s.get_window().set_cursor(Gdk.Cursor.new_from_name(s.get_display(), CURSORS[edge]) if edge else None)


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        assert pick([], None) is None
        assert pick([('a', 'Paused'), ('b', 'Playing')], 'a') == 'b'
        assert pick([('a', 'Playing'), ('b', 'Playing')], 'b') == 'b'
        assert pick([('a', 'Stopped'), ('b', 'Paused')], None) == 'b'
        assert resize_scale(1, 100, 50) == 1.5 and resize_scale(1, 100, -90) == SCALE_MIN and resize_scale(2, 100, 10) == SCALE_MAX
        assert clamp_scale(5) == SCALE_MAX and clamp_scale(0.1) == SCALE_MIN and clamp_scale(1.1) == 1.1
        assert panel_w(0) == CW and panel_w(1) == W and CW < panel_w(0.5) < W
        print('ok'); sys.exit()
    # второй запуск (двойной клик по ярлыку) молча выходит: имя на шине уже занято первым
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    if bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'RequestName',
                     GLib.Variant('(su)', ('io.github.tunepeek', 4)), GLib.VariantType('(u)'), 0, -1, None).unpack()[0] != 1:
        sys.exit()
    Player(); Gtk.main()
