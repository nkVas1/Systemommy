"""GPU temperature reader.

Uses NVML (NVIDIA Management Library) when available, falls back to WMI
or Open Hardware Monitor on Windows.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GpuReading:
    """Snapshot of GPU thermal and usage state."""

    temperature: float | None  # °C
    usage_percent: float | None  # 0‒100, ``None`` if unavailable
    name: str  # e.g. "NVIDIA GeForce RTX 3060 Ti"


def _read_nvml() -> GpuReading | None:
    """Read GPU temperature via NVIDIA NVML."""
    try:
        import pynvml  # type: ignore[import-untyped]

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(
            handle, pynvml.NVML_TEMPERATURE_GPU
        )
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            usage = float(util.gpu)
        except Exception:  # noqa: BLE001
            usage = None
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        pynvml.nvmlShutdown()
        return GpuReading(temperature=float(temp), usage_percent=usage, name=name)
    except Exception:  # noqa: BLE001
        logger.debug("NVML read failed.", exc_info=True)
    return None


def _read_ohm_gpu() -> GpuReading | None:
    """Read GPU temperature via Open Hardware Monitor WMI."""
    if platform.system() != "Windows":
        return None
    try:
        import wmi  # type: ignore[import-untyped]

        w = wmi.WMI(namespace=r"root\OpenHardwareMonitor")
        sensors = w.Sensor()
        gpu_temps: list[float] = []
        gpu_name = "GPU"
        for sensor in sensors:
            if sensor.SensorType == "Temperature" and "gpu" in sensor.Name.lower():
                gpu_temps.append(float(sensor.Value))
            if sensor.SensorType == "Clock" and "gpu" in sensor.Name.lower():
                gpu_name = sensor.Parent if hasattr(sensor, "Parent") else "GPU"
        if gpu_temps:
            return GpuReading(
                temperature=round(max(gpu_temps), 1),
                usage_percent=None,
                name=str(gpu_name),
            )
    except Exception:  # noqa: BLE001
        logger.debug("OHM GPU read failed.", exc_info=True)
    return None


def read_gpu() -> GpuReading:
    """Return current GPU temperature and usage."""
    reading = _read_nvml()
    if reading is not None:
        return reading

    reading = _read_ohm_gpu()
    if reading is not None:
        return reading

    return GpuReading(temperature=None, usage_percent=None, name="Unknown GPU")
