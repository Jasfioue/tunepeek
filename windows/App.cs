// Tunepeek — мини-плеер поверх всех окон: показывает, что играет (YouTube/SoundCloud в браузере, Spotify... — всё, что видит медиа-панель Windows).
// Видна только обложка; на новом треке название выезжает на 5 с. Навести на обложку — раскрыть.
// ЛКМ по кнопкам — назад/пауза/вперёд, ЛКМ+тянуть — двигать, колесо — размер, ПКМ — выход. Мимо панели клики проходят насквозь.
// Первый запуск копирует exe в %LOCALAPPDATA%\Tunepeek и прописывает автозапуск.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Microsoft.Win32;
using Windows.Media.Control;
using MediaManager = Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager;
using Session = Windows.Media.Control.GlobalSystemMediaTransportControlsSession;

static class Program
{
    [STAThread]
    static void Main()
    {
        var dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Tunepeek");
        var target = Path.Combine(dir, "Tunepeek.exe");
        var self = Environment.ProcessPath;
        if (!string.Equals(self, target, StringComparison.OrdinalIgnoreCase))
        {
            // запущен из «Загрузок»: ставим себя в постоянное место и запускаем оттуда
            try { Directory.CreateDirectory(dir); File.Copy(self, target, true); }
            catch (IOException) { } // уже установлен и запущен — exe занят, оставляем как есть
            if (File.Exists(target)) Process.Start(target);
            return;
        }
        var run = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
        run.SetValue("Tunepeek", $"\"{target}\"");
        run.DeleteValue("MiniPlayer", false); // автозапуск от старого имени, иначе при входе стартуют оба
        using var one = new Mutex(true, "Tunepeek.single", out var first);
        if (!first) return;
        new Application().Run(new PlayerWindow());
    }
}

class PlayerWindow : Window
{
    const double W = 270, H = 64, ART = 48, PAD = 8, MARGIN = 16, CW = ART + 2 * PAD;
    const int SHOW_MS = 5000, HOVER_OUT_MS = 1500;
    const double SCALE_MIN = 0.75, SCALE_MAX = 2;
    static readonly RegistryKey settings = Registry.CurrentUser.CreateSubKey(@"Software\Tunepeek");

    MediaManager mgr;
    Session cur;
    string curId, track;
    readonly Border panel, art;
    readonly Canvas content, buttons = new();
    readonly TextBlock title, artist, source, playBtn;
    readonly DispatcherTimer hideTimer = new();
    bool hover, busy;
    double scale = 1;
    Point? drag;

    public PlayerWindow()
    {
        WindowStyle = WindowStyle.None; AllowsTransparency = true; Background = Brushes.Transparent; // пиксели с альфой 0 пропускают клики
        ResizeMode = ResizeMode.NoResize; ShowInTaskbar = false; ShowActivated = false; Topmost = true;
        var wa = SystemParameters.WorkArea;
        Left = wa.Right - W - MARGIN; Top = wa.Top + MARGIN;

        TextBlock T(double size, double opacity, FontWeight weight) => new()
        {
            FontSize = size, Opacity = opacity, FontWeight = weight, Foreground = new SolidColorBrush(Color.FromRgb(237, 240, 245)),
            TextTrimming = TextTrimming.CharacterEllipsis, Width = W - CW - PAD,
        };
        title = T(13, 1, FontWeights.Bold); artist = T(11, 0.65, FontWeights.Normal);
        source = T(9, 0.35, FontWeights.Normal); source.TextAlignment = TextAlignment.Right;
        content = new Canvas { ClipToBounds = true, Margin = new Thickness(0, 0, CW, 0), Opacity = 0 };
        Canvas.SetLeft(title, PAD); Canvas.SetTop(title, 4);
        Canvas.SetLeft(artist, PAD); Canvas.SetTop(artist, 22);
        Canvas.SetLeft(source, PAD); Canvas.SetTop(source, 41);
        content.Children.Add(title); content.Children.Add(artist); content.Children.Add(source);
        content.Children.Add(buttons);
        double x = PAD;
        foreach (var (glyph, act) in new (string, Func<Session, Task>)[] {
            ("", s => s.TrySkipPreviousAsync().AsTask()), ("", s => s.TryTogglePlayPauseAsync().AsTask()),
            ("", s => s.TrySkipNextAsync().AsTask()) })
        {
            var b = new TextBlock { Text = glyph, FontFamily = new FontFamily("Segoe MDL2 Assets"), FontSize = 13,
                                    Foreground = title.Foreground, Background = Brushes.Transparent, Padding = new Thickness(4), Cursor = Cursors.Hand };
            b.MouseLeftButtonDown += async (_, e) => { e.Handled = true; if (cur != null) { await act(cur); await Task.Delay(200); await Poll(); } };
            Canvas.SetLeft(b, x - 4); Canvas.SetTop(b, 38); buttons.Children.Add(b);
            if (glyph == "") playBtn = b;
            x += 28;
        }
        panel = new Border { Width = CW, HorizontalAlignment = HorizontalAlignment.Right, CornerRadius = new CornerRadius(12),
                             Background = new SolidColorBrush(Color.FromArgb(153, 33, 38, 48)), Child = content };
        art = new Border { Width = ART, Height = ART, CornerRadius = new CornerRadius(8), Margin = new Thickness(PAD), Opacity = 0.9,
                           HorizontalAlignment = HorizontalAlignment.Right, Background = new SolidColorBrush(Color.FromArgb(20, 255, 255, 255)),
                           Child = new TextBlock { Text = "♪", FontSize = 20, Opacity = 0.5, Foreground = Brushes.White,
                                                   HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center } };
        Content = new Grid { Children = { panel, art }, Width = W, Height = H };
        Width = W; Height = H;
        SetScale((settings.GetValue("Scale") as int? ?? 100) / 100.0);

        hideTimer.Tick += (_, _) => { hideTimer.Stop(); if (!hover) Animate(0); };
        MouseEnter += (_, _) => { hover = true; Expand(0); };
        MouseLeave += (_, _) => { hover = false; Expand(HOVER_OUT_MS); };
        MouseLeftButtonDown += (_, e) => { drag = e.GetPosition(this); CaptureMouse(); };
        MouseLeftButtonUp += (_, _) => { drag = null; ReleaseMouseCapture(); };
        MouseMove += (_, e) => { if (drag is Point d) { var p = PointToScreenDip(e.GetPosition(this)); Left = p.X - d.X; Top = p.Y - d.Y; } };
        MouseRightButtonUp += (_, _) => Close();
        MouseWheel += (_, e) => { SetScale(scale + Math.Sign(e.Delta) * 0.1); settings.SetValue("Scale", (int)Math.Round(scale * 100)); };

        SourceInitialized += (_, _) =>
        {
            // не воровать фокус у игры и не показываться в Alt+Tab
            var h = new WindowInteropHelper(this).Handle;
            SetWindowLong(h, GWL_EXSTYLE, GetWindowLong(h, GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW);
        };
        Loaded += async (_, _) =>
        {
            mgr = await MediaManager.RequestAsync();
            await Poll();
            // shortcut: опрос раз в секунду вместо подписки на события сессий — проще, задержка ≤1 с
            var t = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            t.Tick += async (_, _) => await Poll();
            t.Start();
        };
    }

    void SetScale(double s)
    {
        s = Math.Round(Math.Clamp(s, SCALE_MIN, SCALE_MAX), 2);
        Left += W * (scale - s); // правый край стоит на месте
        scale = s; Width = W * s; Height = H * s;
        ((Grid)Content).LayoutTransform = new ScaleTransform(s, s);
    }

    Point PointToScreenDip(Point p)
    {
        var s = PointToScreen(p);
        return PresentationSource.FromVisual(this).CompositionTarget.TransformFromDevice.Transform(s);
    }

    async Task Poll()
    {
        if (busy || mgr == null) return;
        busy = true;
        try
        {
            var sessions = mgr.GetSessions();
            curId = Picker.Pick(sessions.Select(s => (s.SourceAppUserModelId, s.GetPlaybackInfo().PlaybackStatus.ToString())).ToList(), curId);
            cur = sessions.FirstOrDefault(s => s.SourceAppUserModelId == curId);
            if (cur == null)
            {
                // ничего не играет — панель всё равно видна, иначе после запуска кажется, что плеер не открылся
                if (track != "") { track = ""; title.Text = "Ничего не играет"; artist.Text = source.Text = ""; SetArt(null); buttons.Visibility = Visibility.Hidden; Expand(SHOW_MS); }
                if (!IsVisible) Show();
                return;
            }
            buttons.Visibility = Visibility.Visible;
            var playing = cur.GetPlaybackInfo().PlaybackStatus == GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing;
            playBtn.Text = playing ? "" : "";
            var props = await cur.TryGetMediaPropertiesAsync();
            var key = $"{curId}\n{props.Title}\n{props.Artist}";
            if (key != track)
            {
                track = key;
                title.Text = string.IsNullOrEmpty(props.Title) ? "Без названия" : props.Title;
                artist.Text = props.Artist;
                source.Text = Path.GetFileNameWithoutExtension(curId.Split('!').Last());
                SetArt(await LoadArt(props.Thumbnail));
                Expand(SHOW_MS);
            }
            if (!IsVisible) Show();
            // каждый тик снова наверх — игра могла перекрыть
            SetWindowPos(new WindowInteropHelper(this).Handle, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        }
        catch (COMException) { } // сессия закрылась посреди опроса — следующий тик разберётся
        finally { busy = false; }
    }

    void SetArt(Brush b)
    {
        art.Background = b ?? new SolidColorBrush(Color.FromArgb(20, 255, 255, 255));
        ((TextBlock)art.Child).Visibility = b == null ? Visibility.Visible : Visibility.Collapsed;
    }

    static async Task<Brush> LoadArt(Windows.Storage.Streams.IRandomAccessStreamReference thumb)
    {
        if (thumb == null) return null;
        try
        {
            using var ws = await thumb.OpenReadAsync();
            var ms = new MemoryStream();
            await ws.AsStreamForRead().CopyToAsync(ms);
            ms.Position = 0;
            var bmp = new BitmapImage();
            bmp.BeginInit(); bmp.CacheOption = BitmapCacheOption.OnLoad; bmp.StreamSource = ms; bmp.EndInit(); bmp.Freeze();
            // UniformToFill обрезает до квадрата (у YouTube превью 16:9)
            return new ImageBrush(bmp) { Stretch = Stretch.UniformToFill };
        }
        catch (Exception) { return null; }
    }

    void Expand(int ms)
    {
        hideTimer.Stop();
        Animate(1);
        if (ms > 0) { hideTimer.Interval = TimeSpan.FromMilliseconds(ms); hideTimer.Start(); }
    }

    void Animate(double k)
    {
        var d = TimeSpan.FromMilliseconds(330);
        panel.BeginAnimation(WidthProperty, new DoubleAnimation(k > 0 ? W : CW, d) { EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut } });
        content.BeginAnimation(OpacityProperty, new DoubleAnimation(k, d));
    }

    const int GWL_EXSTYLE = -20, WS_EX_NOACTIVATE = 0x08000000, WS_EX_TOOLWINDOW = 0x80;
    const uint SWP_NOSIZE = 1, SWP_NOMOVE = 2, SWP_NOACTIVATE = 0x10;
    static readonly IntPtr HWND_TOPMOST = new(-1);
    [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int i);
    [DllImport("user32.dll")] static extern int SetWindowLong(IntPtr h, int i, int v);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint f);
}
