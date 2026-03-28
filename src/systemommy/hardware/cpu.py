"""CPU temperature reader.

Uses platform-specific APIs:
- Windows: WMI (MSAcpi_ThermalZoneTemperature) + psutil
- Linux:   psutil sensors (``/sys/class/thermal``)

Falls back to ``None`` when temperature cannot be read.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CpuReading:
    """Snapshot of CPU thermal and usage state."""

    temperature: float | None  # °C, ``None`` if unavailable
    usage_percent: float  # 0‒100


def _read_temperature_psutil() -> float | None:
    """Attempt to read CPU temperature through psutil."""
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
    if platform.system() != "Windows":
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


def read_cpu() -> CpuReading:
    """Return current CPU temperature and usage."""
    usage = psutil.cpu_percent(interval=0)

    # Try sources in order of reliability
    temp = _read_temperature_psutil()
    if temp is None and platform.system() == "Windows":
        temp = _read_temperature_ohm()
    if temp is None and platform.system() == "Windows":
        temp = _read_temperature_wmi()

    return CpuReading(temperature=temp, usage_percent=usage)
