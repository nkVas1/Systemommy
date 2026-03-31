# Systemommy

**Hardware temperature monitor with overlay for Windows 11.**

Systemommy reads CPU and GPU temperatures in real time and displays them as a
minimal, always-on-top overlay that works over games and applications. When
temperatures reach critical levels it plays an alert sound and can automatically
throttle performance to protect your hardware.

---

## Features

- **Live overlay** — semi-transparent, click-through temperature display on top of all windows.
- **Temperature graphs** — Metrics tab with line graphs (last 15/30 min or full session) and session statistics.
- **Critical alerts** — sound and visual warnings when CPU or GPU temperatures exceed thresholds.
- **Automatic thermal correction** — reversible CPU/GPU throttling when temps are dangerously high (with user permission).
- **Settings UI** — tabbed, skeuomorphic hacker-themed interface for full customisation.
- **System tray** — minimises to tray; double-click to open settings.
- **File logging** — logs to `~/.systemommy/systemommy.log` for diagnostics.
- **Single-file launch** — just run `run.bat` on Windows.

## Quick Start

### Requirements

- **Windows 7 / 8 / 10 / 11**
- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
  - During installation check **"Add Python to PATH"**

### Launch

```
run.bat
```

That's it. The launcher will:
1. Find Python on your system (supports `py` launcher, `python`, `python3`)
2. Create a virtual environment
3. Install dependencies from `requirements.txt` (fast, no build step)
4. Start Systemommy

### Launcher Options

| Flag | Description |
|------|-------------|
| `run.bat --force` | Delete virtual environment and reinstall everything |
| `run.bat --console` | Launch with a visible console window for diagnostics |
| `run.bat --help` | Show all available options |

### Manual launch (any OS, for development)

```bash
pip install -r requirements.txt
set PYTHONPATH=src
python -m systemommy
```

## Troubleshooting

### Console window closes instantly

Delete the `venv` folder and run `run.bat` again — the script shows step-by-step
progress and pauses on any error so you can read the message.

Or run with diagnostics:

```
run.bat --console
```

### Something went wrong — full reinstall

```
run.bat --force
```

This deletes the virtual environment and installs everything from scratch.

### CPU temperature shows "N/A"

On Windows, CPU temperature is **not** available through standard APIs — it
requires a kernel-level driver.  Systemommy tries 9 different sources
automatically:

| Source | Needs | Notes |
|--------|-------|-------|
| psutil | — | Works on Linux / macOS only |
| sysfs hwmon | — | Linux only |
| Open Hardware Monitor (WMI) | OHM running + `wmi` pip pkg | Best accuracy |
| LibreHardwareMonitor (WMI) | LHWM running + `wmi` pip pkg | Best accuracy |
| OHM (PowerShell) | OHM running | No extra pip packages |
| LHWM (PowerShell) | LHWM running | No extra pip packages |
| ThermalZoneInfo (perf counter) | Windows 10 1903+ | No admin, no extra software |
| MSAcpi (PowerShell) | Admin on some systems | Often inaccurate (~28 °C) |
| WMI package | `wmi` pip pkg | Last resort |

**Recommended fix:** Install and run
[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
(free, open source).  Run it as Administrator and leave it in the background —
Systemommy will detect it automatically.

### Installation timeouts on slow connections

PySide6 is a large package (~570 MB). On slow connections pip may time out.
Pre-download the packages on a fast connection:

```bash
python -m venv venv
venv\Scripts\activate.bat
pip download --dest .wheels -r requirements.txt
```

Then run `run.bat` — it detects the `.wheels` folder and installs offline.

## Architecture

```
src/systemommy/
├── __main__.py          # Entry point
├── app.py               # Application controller
├── config.py            # JSON settings persistence
├── constants.py         # Thresholds, colours, defaults
├── hardware/
│   ├── cpu.py           # CPU temperature (9-level fallback: psutil / sysfs / OHM / LHWM / ThermalZoneInfo / MSAcpi / WMI)
│   ├── gpu.py           # GPU temperature (7-level fallback: NVML / nvidia-smi / sysfs / OHM / LHWM)
│   ├── history.py       # Temperature history for graphs
│   ├── info.py          # Hardware detection & thresholds
│   ├── monitor.py       # Polling orchestrator (Qt signals)
│   └── thermal.py       # Reversible CPU/GPU throttling
├── overlay/
│   └── widget.py        # Transparent always-on-top widget
├── alerts/
│   └── manager.py       # Threshold evaluation, sound, correction prompts
└── ui/
    ├── main_window.py   # Tabbed settings (Dashboard, Overlay, Alerts, Thermal, Metrics)
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

## Development

### Running tests

```bash
pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v
```

On Windows (no display server needed):

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## License

MIT
