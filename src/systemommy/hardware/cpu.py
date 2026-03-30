"""CPU temperature reader.

Uses platform-specific APIs with a multi-level fallback chain:

- **psutil**  ``sensors_temperatures()`` (Linux / macOS / FreeBSD).
- **sysfs**   Direct read from ``/sys/class/thermal`` and ``/sys/class/hwmon``
  (Linux, works even when psutil's sensor list is empty).
- **PowerShell / WMI**  ``MSAcpi_ThermalZoneTemperature`` via ``subprocess``
  (Windows — no ``wmi`` pip package required).
- **Open Hardware Monitor**  OHM WMI namespace (Windows, needs OHM running).
- **WMI python package**  ``wmi`` pip package fallback (Windows).

Falls back to ``None`` when temperature cannot be read by any method.
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
            timeout=5,
            check=False,
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
            return round(max(values), 1)
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
            if sensor.SensorType == "Temperature" and "cpu" in sensor.Name.lower():
                cpu_temps.append(float(sensor.Value))
        if cpu_temps:
            return round(max(cpu_temps), 1)
    except Exception:  # noqa: BLE001
        logger.debug("OHM temperature read failed.", exc_info=True)
    return None


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def read_cpu() -> CpuReading:
    """Return current CPU temperature and usage.

    Tries multiple sources in order of reliability:
    psutil → sysfs (Linux) → PowerShell (Windows) → OHM → WMI package.
    """
    usage = psutil.cpu_percent(interval=0)

    # Try sources in order of reliability
    temp = _read_temperature_psutil()
    if temp is None and _IS_LINUX:
        temp = _read_temperature_sysfs()
    if temp is None and _IS_WINDOWS:
        temp = _read_temperature_powershell()
    if temp is None and _IS_WINDOWS:
        temp = _read_temperature_ohm()
    if temp is None and _IS_WINDOWS:
        temp = _read_temperature_wmi()

    return CpuReading(temperature=temp, usage_percent=usage)
