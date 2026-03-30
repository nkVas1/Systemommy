# Systemommy — Development Guide

> Comprehensive project knowledge base for developers and AI agents.
> Read this file to understand the project, its architecture, and future plans.

---

## What is Systemommy?

**Systemommy** is a hardware temperature monitoring application for Windows 11
(also works on Windows 10 and partially on Linux). It provides:

- **Real-time overlay** — a semi-transparent, click-through temperature display
  that stays on top of all windows, including fullscreen games.
- **Critical temperature alerts** — audible and visual warnings when CPU or GPU
  temperatures exceed configurable thresholds.
- **Automatic thermal correction** — reversible CPU/GPU throttling when
  temperatures reach dangerous levels.
- **Settings UI** — a tabbed, skeuomorphic hacker-themed interface for all
  configuration.
- **System tray** — minimises to tray with quick-access context menu.

---

## Tech Stack

| Component        | Technology                                      |
|------------------|-------------------------------------------------|
| Language         | Python 3.10+                                    |
| UI Framework     | PySide6 (Qt 6)                                  |
| Hardware access  | psutil, WMI, NVML (pynvml), OHM, LHWM          |
| Configuration    | JSON (`~/.systemommy/config.json`)              |
| Tests            | pytest + pytest-qt                              |
| Entry point      | `python -m systemommy` / `run.bat`              |
| Package layout   | `src/systemommy/` (src-layout)                  |

---

## Architecture

```
src/systemommy/
├── __init__.py          # Package metadata (__version__, __app_name__)
├── __main__.py          # Entry point — calls app.run_application()
├── app.py               # SystemommyApp controller — wires all components
├── config.py            # AppConfig dataclass + JSON persistence
├── constants.py         # Thresholds, colours, default values
├── hardware/
│   ├── __init__.py      # Re-exports: CpuReading, GpuReading, HardwareMonitor, etc.
│   ├── cpu.py           # CPU temp reading (psutil → sysfs → OHM → LHWM → OHM PS → LHWM PS → PowerShell → WMI)
│   ├── gpu.py           # GPU temp reading (NVML → nvidia-smi → sysfs → OHM → LHWM → OHM PS → LHWM PS)
│   ├── history.py       # TemperatureHistory — timestamped ring-buffer for graphs
│   ├── info.py          # Hardware detection & threshold estimation
│   ├── monitor.py       # QTimer-based polling, emits HardwareSnapshot via Signal
│   └── thermal.py       # Reversible CPU/GPU throttling (powercfg, NVML)
├── overlay/
│   ├── __init__.py      # Re-exports: OverlayWidget
│   └── widget.py        # Frameless, transparent, always-on-top overlay
├── alerts/
│   ├── __init__.py      # Re-exports: AlertManager
│   └── manager.py       # Threshold evaluation, sound alerts, correction prompts
└── ui/
    ├── __init__.py      # Re-exports: MainWindow, SystemTray
    ├── main_window.py   # Tabbed settings (Dashboard, Overlay, Alerts, Thermal, Metrics)
    ├── theme.py         # QSS stylesheet — hacker/terminal aesthetic
    └── tray.py          # System tray icon and context menu
```

### Data Flow

```
HardwareMonitor (QTimer)
    ├── read_cpu() → CpuReading
    └── read_gpu() → GpuReading
           │
           ▼
    HardwareSnapshot
           │
    ┌──────┼──────────┬──────────────┐
    ▼      ▼          ▼              ▼
Overlay  MainWindow  AlertManager  TemperatureHistory
Widget   Dashboard     │            (ring-buffer)
         Metrics       ├── alert_triggered → status bar
                       └── ThermalCorrector → powercfg / NVML
```

### Signal Architecture

All inter-component communication uses Qt signals:

- `HardwareMonitor.reading_updated(HardwareSnapshot)` → overlay, dashboard, alerts, history
- `AlertManager.alert_triggered(str, str)` → main window status bar
- `_OverlayTab.changed()` / `_AlertsTab.changed()` / `_ThermalTab.changed()` → config save + overlay refresh
- `SystemTray.activated(reason)` → show settings on double-click

---

## Design Theme

Skeuomorphic terminal / hacker aesthetic:

| Element       | Colour    | Hex       |
|---------------|-----------|-----------|
| Accent        | Green     | `#39ff14` |
| Warning       | Gold      | `#ffd700` |
| Critical      | Red       | `#ff2d2d` |
| Info          | Purple    | `#b000ff` |
| Background    | Dark      | `#0a0a0a` |
| Panel         | Dark grey | `#141414` |
| Widget BG     | Dark grey | `#1c1c1c` |
| Border        | Grey      | `#2a2a2a` |
| Text          | Light     | `#d0d0d0` |
| Text dim      | Dim grey  | `#666666` |

Fonts: `Consolas` monospace family. CRT scanline overlay effect on panels.

---

## Code Conventions

- **Python 3.10+** — use `from __future__ import annotations` for newer type syntax.
- **Type hints everywhere** — all functions, methods, return types.
- **Frozen dataclasses** for immutable data (readings).
- **Mutable dataclasses** for config (settings that change).
- **`noqa: BLE001`** on broad exception handlers for external/platform APIs.
- **`noqa: N802`** on Qt method overrides (`paintEvent`, `closeEvent`).
- **Logging** — `logging.getLogger(__name__)` per module; no `print()`.
- **Constants** — all defaults in `constants.py`, imported where needed.
- **Imports** — sorted, grouped: stdlib → third-party → local.

---

## Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (Linux — needs offscreen platform)
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v

# Run tests (Windows)
python -m pytest tests/ -v
```

Test structure follows source structure:
- `test_config.py` — config defaults, persistence, round-trip
- `test_constants.py` — threshold ordering, colour format
- `test_hardware.py` — data structure creation, immutability
- `test_history.py` — temperature history recording, recent/full queries, ring-buffer, truthiness
- `test_thermal.py` — corrector initial state, no-op restore
- `test_overlay.py` — `_temp_color` helper threshold logic
- `test_alerts.py` — alert evaluation, cooldown, threshold validation
- `test_fallbacks.py` — CPU/GPU temperature fallback chains (incl. OHM/LHWM PowerShell)
- `test_info.py` — hardware detection, TjMax estimation, threshold calculation
- `test_metrics_graph.py` — graph data flow, history sharing, tab-switch refresh
- `test_launcher_script.py` — run.bat structure validation

---

## Known Issues / Areas for Improvement

### High Priority
- [x] **Temperature sensors on Linux** — sysfs `/sys/class/hwmon` direct reading
      is now an additional fallback.
- [x] **Console window spawning** — all subprocess calls now use
      `CREATE_NO_WINDOW` on Windows to prevent visible console flashing.
- [x] **CPU temperature accuracy** — fallback chain reordered so OHM /
      LibreHardwareMonitor are tried before the unreliable MSAcpi WMI source.
- [x] **Metrics graphs blank** — the graph widget never received data because
      an empty `TemperatureHistory` was falsy (``__len__`` = 0), causing
      ``history or TemperatureHistory()`` to create a disconnected instance.
      Fixed with an explicit ``is not None`` check and a ``__bool__`` override.
- [x] **Graph not refreshed on tab switch** — switching to the Metrics tab
      now immediately refreshes the graph via ``currentChanged`` signal.
- [x] **CPU temp fallback without wmi package** — added PowerShell-based
      OHM and LHWM queries that work without the ``wmi`` pip package.
- [x] **GPU LHWM fallback** — added LibreHardwareMonitor support for GPU
      temperature reading (via ``wmi`` package and PowerShell subprocess).
- [ ] **AMD GPU support** — currently only NVIDIA via NVML; add ROCm-SMI
      or ADL for AMD GPUs.
- [ ] **Multi-GPU support** — current code reads only GPU index 0.

### Medium Priority
- [x] **Temperature history** — Metrics tab with interactive line graph,
      three view modes (15 min / 30 min / full session), and session
      statistics (min/max/avg).
- [x] **Log file output** — file logging to `~/.systemommy/systemommy.log`.
- [ ] **Per-core CPU temperatures** — show individual core temps, not just max.
- [ ] **Overlay drag-to-position** — let users drag the overlay to reposition
      instead of manual X/Y entry.
- [ ] **Hotkey support** — global hotkey to toggle overlay visibility.
- [ ] **Auto-start on boot** — implement the `start_with_windows` config option
      (currently stored but not wired).

### Low Priority / Future
- [ ] **Tray icon with live temp** — render current temperature into the tray icon.
- [ ] **Plugin system** — allow third-party sensor plugins.
- [ ] **Localization (i18n)** — support multiple UI languages.
- [ ] **Notification integration** — Windows toast notifications for alerts.
- [ ] **Dark/light theme toggle** — currently dark-only.
- [ ] **Export/import config** — backup/restore settings file.
- [ ] **FPS overlay** — optional FPS counter alongside temperature.

---

## Launcher (`run.bat`)

The launcher is designed for a zero-friction experience on Windows 7–11:

1. **Finds Python automatically** — checks `py -3` (Windows Python Launcher),
   `python`, and `python3` in order; skips the Microsoft Store redirect stub.
2. **Creates a virtual environment** — isolated from system Python.
3. **Detects broken venvs** — if the venv's `python.exe` can't start, the
   launcher deletes and recreates it automatically.
4. **Installs via `pip install -r requirements.txt`** — installs only runtime
   dependencies (PySide6, psutil) as pre-built binary wheels. No build
   isolation, no setuptools download — fast and reliable even on slow networks.
5. **Sets `PYTHONPATH`** — points to `src/` so Python can find the `systemommy`
   package without a full package install.
6. **Offline `.wheels` cache** — detects pre-downloaded wheels and installs
   from them when both `PySide6*.whl` and `psutil*.whl` are present. Falls
   back to online PyPI install automatically if local cache is incomplete.
7. **Launches with `pythonw`** — no console window cluttering the desktop.

### Launcher flags

| Flag | Effect |
|------|--------|
| `--force` | Delete venv and reinstall everything from scratch |
| `--console` | Launch the app with a visible console (for diagnostics) |
| `--help` | Show usage information |

---

## Build & Distribution

Currently single-file launcher (`run.bat`). Future distribution options:
- **PyInstaller** — create standalone `.exe` for Windows.
- **NSIS/Inno Setup** — Windows installer with Start Menu shortcuts.
- **GitHub Releases** — automated release builds via CI.

---

## File Reference

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package metadata, dependencies, pytest config |
| `requirements.txt` | Pip-compatible dependency list |
| `run.bat` | One-click launcher for Windows (auto-install + launch) |
| `.gitignore` | Excludes venv, __pycache__, build artifacts |
| `README.md` | User-facing documentation |
| `DEVELOPMENT.md` | This file — developer knowledge base |
