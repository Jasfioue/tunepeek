# Tunepeek

[![Скачать последнюю версию](https://img.shields.io/github/v/release/Jasfioue/tunepeek?style=for-the-badge&label=%D0%A1%D0%BA%D0%B0%D1%87%D0%B0%D1%82%D1%8C&color=6d3fd1)](https://github.com/Jasfioue/tunepeek/releases/latest)
[![Загрузки](https://img.shields.io/github/downloads/Jasfioue/tunepeek/total?style=for-the-badge&label=%D0%97%D0%B0%D0%B3%D1%80%D1%83%D0%B7%D0%BA%D0%B8)](https://github.com/Jasfioue/tunepeek/releases)

Крошечная панель «что сейчас играет» поверх всех окон, даже поверх полноэкранных игр и видео.
Видит YouTube и SoundCloud в браузере, Spotify, VLC: всё, что отдаёт системе информацию о треке.

![Раскрытая панель](docs/expanded.png)

В свёрнутом виде видна только обложка. Когда начинается новый трек, на 5 секунд выезжает название; если навести курсор, панель раскроется.

| Свёрнута | Ничего не играет | Увеличена |
|---|---|---|
| ![](docs/collapsed.png) | ![](docs/idle.png) | ![](docs/large.png) |

| Действие | Что делает |
|---|---|
| ЛКМ по кнопкам | назад / пауза / вперёд |
| ЛКМ + тянуть | переместить |
| Тянуть за край | изменить размер (75–200 %, запоминается) |
| ПКМ | закрыть |
| Значок «Вкусно — и точка» в углу | пасхалка 🍟 (только в [1.1](https://github.com/Jasfioue/tunepeek/releases/tag/v1.1)) |

Клики мимо панели проходят насквозь.

## Linux (`linux/`)

Python 3 + GTK 3, данные берёт по MPRIS через D-Bus. Зависимостей сверх системных нет.

```
python3 linux/tunepeek.py            # запуск
python3 linux/tunepeek.py --selftest # самопроверка
```

## Windows (`windows/`)

C# / WPF, данные берёт из медиа-сессий Windows (GSMTC). Готовый `Tunepeek.exe` — в [последнем релизе](https://github.com/Jasfioue/tunepeek/releases/latest).
При первом запуске копирует себя в `%LOCALAPPDATA%\Tunepeek` и добавляет себя в автозапуск (`HKCU\...\Run\Tunepeek`).
Чтобы удалить: закройте панель (ПКМ), удалите эту папку и значение `Tunepeek` в автозапуске.

Сборка (.NET 8 SDK):

```
cd windows && dotnet publish -c Release -o out
```
