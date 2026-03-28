# Systemommy

**Hardware temperature monitor with overlay for Windows 11.**

Systemommy reads CPU and GPU temperatures in real time and displays them as a
minimal, always-on-top overlay that works over games and applications. When
temperatures reach critical levels it plays an alert sound and can automatically
throttle performance to protect your hardware.

---

## Features

- **Live overlay** — semi-transparent, click-through temperature display on top of all windows.
- **Critical alerts** — sound and visual warnings when CPU or GPU temperatures exceed thresholds.
- **Automatic thermal correction** — reversible CPU/GPU throttling when temps are dangerously high (with user permission).
- **Settings UI** — tabbed, skeuomorphic hacker-themed interface for full customisation.
- **System tray** — minimises to tray; double-click to open settings.
- **Single-file launch** — just run `run.bat` on Windows.

## Quick Start

### Requirements

- **Windows 11** (or 10)
- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)

### Launch

```
run.bat
```

The launcher creates a virtual environment, installs dependencies automatically,
and starts the application. No manual commands needed.

### Manual launch (any OS, for development)

```bash
pip install -e .
python -m systemommy
```

## Architecture

```
src/systemommy/
├── __main__.py          # Entry point
├── app.py               # Application controller
├── config.py            # JSON settings persistence
├── constants.py         # Thresholds, colours, defaults
├── hardware/
│   ├── cpu.py           # CPU temperature (psutil / WMI / OHM)
│   ├── gpu.py           # GPU temperature (NVML / OHM)
│   ├── monitor.py       # Polling orchestrator (Qt signals)
│   └── thermal.py       # Reversible CPU/GPU throttling
├── overlay/
│   └── widget.py        # Transparent always-on-top widget
├── alerts/
│   └── manager.py       # Threshold evaluation, sound, correction prompts
└── ui/
    ├── main_window.py   # Tabbed settings window
    ├── theme.py         # QSS stylesheet (hacker / terminal theme)
    └── tray.py          # System tray icon
```

## Theme

Skeuomorphic terminal / hacker aesthetic:

| Element       | Colour    |
|---------------|-----------|
| Accent        | `#39ff14` (green) |
| Warning       | `#ffd700` (gold)  |
| Critical      | `#ff2d2d` (red)   |
| Info          | `#b000ff` (purple)|
| Background    | `#0a0a0a` (dark)  |

Monospace fonts (`Consolas`), CRT scanline overlay, glow effects.

## Configuration

Settings are saved to `~/.systemommy/config.json` and persist across restarts.
All options are accessible from the Settings window (system tray → Settings).

## License

MIT