"""CPU temperature reader.

Uses platform-specific APIs with a multi-level fallback chain:

- **psutil**  ``sensors_temperatures()`` (Linux / macOS / FreeBSD).
- **sysfs**   Direct read from ``/sys/class/thermal`` and ``/sys/class/hwmon``
  (Linux, works even when psutil's sensor list is empty).
- **Open Hardware Monitor**  OHM WMI namespace via ``wmi`` package
  (Windows, needs OHM running and ``wmi`` package installed).
- **LibreHardwareMonitor**  LHWM WMI namespace via ``wmi`` package
  (Windows, needs LHWM running and ``wmi`` package installed).
- **Open Hardware Monitor (PowerShell)**  OHM WMI namespace via
  ``powershell`` subprocess (Windows, needs OHM running — does **not**
  require the ``wmi`` pip package).
- **LibreHardwareMonitor (PowerShell)**  LHWM WMI namespace via
  ``powershell`` subprocess (Windows, needs LHWM running — does **not**
  require the ``wmi`` pip package).
- **Thermal Zone performance counter**
  ``Win32_PerfFormattedData_Counters_ThermalZoneInformation`` via PowerShell
  (Windows 10 1903+ / Windows 11 — no ``wmi`` pip package required, no admin
  privileges required).  More reliable than ``MSAcpi`` on many systems.
- **PowerShell / WMI**  ``MSAcpi_ThermalZoneTemperature`` via ``subprocess``
  (Windows — no ``wmi`` pip package required).  This source often returns
  inaccurate readings (fixed ~28 °C) on many systems and is therefore tried
  late.  Suspiciously low readings (< 15 °C) are rejected.
- **WMI python package**  ``wmi`` pip package fallback (Windows).

Falls back to ``None`` when temperature cannot be read by any method.

Sensor matching
~~~~~~~~~~~~~~~
OHM / LibreHardwareMonitor expose sensors whose *Name* contains labels
like ``"CPU Package"``, ``"CPU Core #1"`` (Intel) **or** ``"Core
(Tctl/Tdie)"``, ``"CCD1 (Tdie)"`` (AMD Ryzen) which do **not** include
the substring ``"cpu"``.  To handle both vendors we match on a broader
set of keywords **and** on the ``Identifier`` property which always
contains ``cpu/`` for processor sensors (e.g.
``/amdcpu/0/temperature/0``, ``/intelcpu/0/temperature/0``).
"""

from __future__ import annotations

import glob as _glob
import logging
import platform
import subprocess
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)

_IS_LINUX = platform.system() == "Linux"
_IS_WINDOWS = platform.system() == "Windows"

# Subprocess creation flag that prevents a visible console window on Windows.
_SUBPROCESS_FLAGS: int = (
    subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
)

# PowerShell may need extra time on first invocation (.NET cold-start).
_PS_TIMEOUT: int = 8

# Keywords that identify a CPU temperature sensor by *Name* in OHM / LHWM.
# Intel names typically include "cpu" ("CPU Package", "CPU Core #1").
# AMD Ryzen names often omit "cpu" ("Core (Tctl/Tdie)", "CCD1 (Tdie)").
_CPU_SENSOR_NAME_KEYWORDS: tuple[str, ...] = (
    "cpu",
    "core",
    "package",
    "tctl",
    "tdie",
    "ccd",
)


def _is_cpu_sensor(sensor) -> bool:
    """Return *True* if *sensor* is a CPU temperature sensor.

    Checks both the sensor ``Name`` (against a broad keyword list) and the
    ``Identifier`` property (which contains ``cpu/`` for processor sensors
    in OHM / LHWM, e.g. ``/amdcpu/0/…``, ``/intelcpu/0/…``).
    """
    name_lower = sensor.Name.lower() if hasattr(sensor, "Name") else ""
    if any(kw in name_lower for kw in _CPU_SENSOR_NAME_KEYWORDS):
        return True
    identifier = ""
    if hasattr(sensor, "Identifier"):
        identifier = str(sensor.Identifier).lower()
    return "cpu/" in identifier


@dataclass(frozen=True)
class CpuReading:
    """Snapshot of CPU thermal and usage state."""

    temperature: float | None  # °C, ``None`` if unavailable
    usage_percent: float  # 0‒100


# ------------------------------------------------------------------
# Fallback readers — ordered by reliability
# ------------------------------------------------------------------


def _read_temperature_psutil() -> float | None:
    """Attempt to read CPU temperature through *psutil*."""
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, RuntimeError):
        # psutil.sensors_temperatures() is not available on all platforms
        return None

    if not temps:
        return None

    # Prioritise "coretemp" (Intel), "k10temp" (AMD), then any first key
    for key in ("coretemp", "k10temp"):
        if key in temps:
            entries = temps[key]
            if entries:
                return max(e.current for e in entries)

    # Fallback: first available sensor group
    first_group = next(iter(temps.values()), [])
    if first_group:
        return max(e.current for e in first_group)
    return None


def _read_temperature_sysfs() -> float | None:
    """Read CPU temperature directly from Linux sysfs.

    Checks two locations:

    1. ``/sys/class/hwmon/hwmon*/temp*_input`` — hardware monitoring drivers
       (coretemp, k10temp, etc.) expose per-core temperatures here.
    2. ``/sys/class/thermal/thermal_zone*/temp`` — kernel thermal zones,
       available even on systems without specific hwmon drivers.

    Returns the maximum temperature found (°C) or ``None``.
    """
    if not _IS_LINUX:
        return None

    temps: list[float] = []

    # 1. hwmon — check for cpu-related sensors
    for name_path in sorted(_glob.glob("/sys/class/hwmon/hwmon*/name")):
        try:
            hwmon_dir = name_path.rsplit("/", 1)[0]
            with open(name_path) as fh:
                name = fh.read().strip().lower()
            # Only read CPU-related hwmon devices.
            # These are the most common Linux CPU thermal sensor drivers:
            # - coretemp: Intel Core/Xeon CPUs
            # - k10temp: AMD Family 10h+ CPUs (Ryzen, EPYC, etc.)
            # - zenpower: Community AMD Zen driver (alternative to k10temp)
            # - cpu_thermal: ARM / SoC CPU thermal driver
            # - acpitz: ACPI thermal zone (generic, may report CPU temp)
            # - soc_thermal: System-on-Chip thermal driver
            if name not in ("coretemp", "k10temp", "zenpower", "cpu_thermal",
                            "acpitz", "soc_thermal"):
                continue
            for temp_input in sorted(_glob.glob(f"{hwmon_dir}/temp*_input")):
                try:
                    with open(temp_input) as fh:
                        val = int(fh.read().strip())
                    # sysfs reports millidegrees Celsius
                    if val > 0:
                        temps.append(val / 1000.0)
                except (ValueError, OSError):
                    continue
        except (ValueError, OSError):
            continue

    if temps:
        return round(max(temps), 1)

    # 2. thermal_zone fallback
    for temp_path in sorted(_glob.glob("/sys/class/thermal/thermal_zone*/temp")):
        try:
            with open(temp_path) as fh:
                val = int(fh.read().strip())
            if val > 0:
                temps.append(val / 1000.0)
        except (ValueError, OSError):
            continue

    if temps:
        return round(max(temps), 1)
    return None


def _read_temperature_thermal_zone_info_ps() -> float | None:
    """Read CPU temperature via Windows performance counter thermal zones.

    Queries ``Win32_PerfFormattedData_Counters_ThermalZoneInformation``
    which is available on Windows 10 1903+ and Windows 11.  Unlike
    ``MSAcpi_ThermalZoneTemperature`` this counter does **not** require
    administrator privileges and often reports more accurate values.

    The ``Temperature`` property is in tenths of Kelvin.
    """
    if not _IS_WINDOWS:
        return None
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "Get-CimInstance"
                    " Win32_PerfFormattedData_Counters_ThermalZoneInformation"
                    " -ErrorAction Stop"
                    " | Where-Object { $_.Name -match 'CPU|Thermal|ACPI' -or"
                    " $_.HighPrecisionTemperature -gt 2732 }"
                    " | ForEach-Object {"
                    " if ($_.HighPrecisionTemperature) {"
                    " $_.HighPrecisionTemperature"
                    " } elseif ($_.Temperature) {"
                    " $_.Temperature * 10"
                    " } }"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT,
            check=False,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            return None
        values: list[float] = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                try:
                    kelvin_tenths = float(line)
                    celsius = kelvin_tenths / 10.0 - 273.15
                    if 15 < celsius < 150:  # sanity + low-reading filter
                        values.append(celsius)
                except ValueError:
                    continue
        if values:
            return round(max(values), 1)
    except Exception:  # noqa: BLE001
        logger.debug(
            "Thermal zone performance counter read failed.", exc_info=True,
        )
    return None


def _read_temperature_powershell() -> float | None:
    """Read CPU temperature via PowerShell on Windows (no ``wmi`` package).

    Uses ``Get-CimInstance MSAcpi_ThermalZoneTemperature`` which queries the
    same WMI data as the ``wmi`` package but through a subprocess call.
    Requires elevated permissions on some systems.
    """
    if not _IS_WINDOWS:
        return None
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "Get-CimInstance MSAcpi_ThermalZoneTemperature"
                    " -Namespace root/wmi -ErrorAction Stop"
                    " | Select-Object -ExpandProperty CurrentTemperature"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT,
            check=False,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            return None
        values: list[float] = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                try:
                    kelvin_tenths = float(line)
                    celsius = kelvin_tenths / 10.0 - 273.15
                    if 0 < celsius < 150:  # sanity check
                        values.append(celsius)
                except ValueError:
                    continue
        if values:
            temp = round(max(values), 1)
            # Reject suspiciously low fixed readings that many boards return
            if temp >= 15.0:
                return temp
    except Exception:  # noqa: BLE001
        logger.debug("PowerShell temperature read failed.", exc_info=True)
    return None


def _read_temperature_wmi() -> float | None:
    """Attempt to read CPU temperature via WMI on Windows."""
    try:
        import wmi  # type: ignore[import-untyped]

        w = wmi.WMI(namespace=r"root\wmi")
        data = w.MSAcpi_ThermalZoneTemperature()
        if data:
            # WMI returns tenths of Kelvin
            kelvin_tenths = max(item.CurrentTemperature for item in data)
            return round(kelvin_tenths / 10.0 - 273.15, 1)
    except Exception:  # noqa: BLE001
        logger.debug("WMI temperature read failed.", exc_info=True)
    return None


def _read_temperature_ohm() -> float | None:
    """Attempt to read CPU temperature via Open Hardware Monitor WMI."""
    if not _IS_WINDOWS:
        return None
    try:
        import wmi  # type: ignore[import-untyped]

        w = wmi.WMI(namespace=r"root\OpenHardwareMonitor")
        sensors = w.Sensor()
        cpu_temps: list[float] = []
        for sensor in sensors:
            if sensor.SensorType == "Temperature" and _is_cpu_sensor(sensor):
                cpu_temps.append(float(sensor.Value))
        if cpu_temps:
            return round(max(cpu_temps), 1)
    except Exception:  # noqa: BLE001
        logger.debug("OHM temperature read failed.", exc_info=True)
    return None


def _read_temperature_lhwm() -> float | None:
    r"""Attempt to read CPU temperature via LibreHardwareMonitor WMI.

    LibreHardwareMonitor (LHWM) is the maintained successor to Open
    Hardware Monitor and exposes the ``root\LibreHardwareMonitor`` WMI
    namespace when running.
    """
    if not _IS_WINDOWS:
        return None
    try:
        import wmi  # type: ignore[import-untyped]

        w = wmi.WMI(namespace=r"root\LibreHardwareMonitor")
        sensors = w.Sensor()
        cpu_temps: list[float] = []
        for sensor in sensors:
            if sensor.SensorType == "Temperature" and _is_cpu_sensor(sensor):
                cpu_temps.append(float(sensor.Value))
        if cpu_temps:
            return round(max(cpu_temps), 1)
    except Exception:  # noqa: BLE001
        logger.debug("LHWM temperature read failed.", exc_info=True)
    return None


def _read_temperature_ohm_ps() -> float | None:
    """Read CPU temperature via OHM WMI namespace using PowerShell.

    This does **not** require the ``wmi`` Python package — it queries the
    ``root/OpenHardwareMonitor`` WMI namespace through a ``powershell``
    subprocess.  Open Hardware Monitor must be running for this to work.

    The filter matches sensors whose *Identifier* contains ``cpu/``
    (reliable across Intel ``/intelcpu/`` and AMD ``/amdcpu/``) **or**
    whose *Name* matches common CPU-thermal keywords.
    """
    if not _IS_WINDOWS:
        return None
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "Get-CimInstance -Namespace root/OpenHardwareMonitor"
                    " -ClassName Sensor -ErrorAction Stop"
                    " | Where-Object {"
                    " $_.SensorType -eq 'Temperature' -and"
                    " ($_.Identifier -match 'cpu/' -or"
                    " $_.Name -match 'cpu|core|package|tctl|tdie|ccd')"
                    "} | Select-Object -ExpandProperty Value"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT,
            check=False,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            return None
        values: list[float] = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                try:
                    val = float(line)
                    if 0 < val < 150:
                        values.append(val)
                except ValueError:
                    continue
        if values:
            return round(max(values), 1)
    except Exception:  # noqa: BLE001
        logger.debug("OHM PowerShell temperature read failed.", exc_info=True)
    return None


def _read_temperature_lhwm_ps() -> float | None:
    r"""Read CPU temperature via LibreHardwareMonitor WMI using PowerShell.

    Same approach as :func:`_read_temperature_ohm_ps` but targeting the
    ``root/LibreHardwareMonitor`` namespace.
    """
    if not _IS_WINDOWS:
        return None
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "Get-CimInstance -Namespace root/LibreHardwareMonitor"
                    " -ClassName Sensor -ErrorAction Stop"
                    " | Where-Object {"
                    " $_.SensorType -eq 'Temperature' -and"
                    " ($_.Identifier -match 'cpu/' -or"
                    " $_.Name -match 'cpu|core|package|tctl|tdie|ccd')"
                    "} | Select-Object -ExpandProperty Value"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT,
            check=False,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            return None
        values: list[float] = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                try:
                    val = float(line)
                    if 0 < val < 150:
                        values.append(val)
                except ValueError:
                    continue
        if values:
            return round(max(values), 1)
    except Exception:  # noqa: BLE001
        logger.debug("LHWM PowerShell temperature read failed.", exc_info=True)
    return None


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def read_cpu() -> CpuReading:
    """Return current CPU temperature and usage.

    Tries multiple sources in order of reliability:
    psutil → sysfs (Linux) → OHM (wmi) → LHWM (wmi) → OHM (PowerShell) →
    LHWM (PowerShell) → ThermalZoneInfo (perf counter) →
    PowerShell MSAcpi → WMI package.

    On Windows the OHM / LibreHardwareMonitor sources are preferred over
    the PowerShell ``MSAcpi_ThermalZoneTemperature`` query because that
    WMI class is often inaccurate (returns a fixed ~28 °C on many boards).

    The ``Win32_PerfFormattedData_Counters_ThermalZoneInformation`` counter
    (available on Windows 10 1903+ / Windows 11) sits between
    OHM/LHWM and MSAcpi — it does not require admin privileges and is more
    accurate than MSAcpi on most systems.
    """
    usage = psutil.cpu_percent(interval=0)

    # Ordered fallback chain — each method is tried only if the previous
    # returned *None*.  A tuple of (reader_function, label, platform_guard).
    _chain: tuple[tuple[object, str, bool], ...] = (
        (_read_temperature_psutil, "psutil", True),
        (_read_temperature_sysfs, "sysfs", _IS_LINUX),
        (_read_temperature_ohm, "OHM (wmi)", _IS_WINDOWS),
        (_read_temperature_lhwm, "LHWM (wmi)", _IS_WINDOWS),
        (_read_temperature_ohm_ps, "OHM (PowerShell)", _IS_WINDOWS),
        (_read_temperature_lhwm_ps, "LHWM (PowerShell)", _IS_WINDOWS),
        (
            _read_temperature_thermal_zone_info_ps,
            "ThermalZoneInfo (perf counter)",
            _IS_WINDOWS,
        ),
        (_read_temperature_powershell, "MSAcpi (PowerShell)", _IS_WINDOWS),
        (_read_temperature_wmi, "WMI package", _IS_WINDOWS),
    )

    temp: float | None = None
    for reader, label, guard in _chain:
        if not guard:
            continue
        temp = reader()  # type: ignore[operator]
        if temp is not None:
            logger.debug("CPU temperature read via %s: %.1f °C", label, temp)
            break

    if temp is None:
        logger.info(
            "CPU temperature unavailable — all fallback methods returned None. "
            "On Windows, install and run LibreHardwareMonitor for reliable readings."
        )

    return CpuReading(temperature=temp, usage_percent=usage)
