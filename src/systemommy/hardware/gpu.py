"""GPU temperature reader.

Uses a multi-level fallback chain:

- **NVML** (pynvml) — best for NVIDIA GPUs when the package is installed.
- **nvidia-smi CLI** — parses ``nvidia-smi`` output; works when pynvml is
  absent but NVIDIA drivers are installed.
- **Linux sysfs / hwmon** — reads ``/sys/class/drm/card*/device/hwmon``
  for AMD / Intel GPUs.
- **Open Hardware Monitor WMI** — Windows only, requires OHM running.
"""

from __future__ import annotations

import glob as _glob
import logging
import platform
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_IS_LINUX = platform.system() == "Linux"
_IS_WINDOWS = platform.system() == "Windows"


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


def _read_nvidia_smi() -> GpuReading | None:
    """Read GPU temperature via ``nvidia-smi`` CLI.

    Works on both Windows and Linux whenever NVIDIA drivers are installed,
    even without the ``pynvml`` Python package.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu,utilization.gpu,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return None
        line = result.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            return None
        temp = float(parts[0])
        try:
            usage = float(parts[1])
        except (ValueError, IndexError):
            usage = None
        name = parts[2] if len(parts) >= 3 else "NVIDIA GPU"
        if 0 < temp < 150:  # sanity check
            return GpuReading(temperature=temp, usage_percent=usage, name=name)
    except Exception:  # noqa: BLE001
        logger.debug("nvidia-smi read failed.", exc_info=True)
    return None


def _read_sysfs_gpu() -> GpuReading | None:
    """Read GPU temperature from Linux sysfs hwmon entries.

    Covers AMD (amdgpu) and Intel (i915) GPUs that expose hwmon sensors
    under ``/sys/class/drm/card*/device/hwmon/``.
    """
    if not _IS_LINUX:
        return None

    # Approach 1: look under /sys/class/drm for GPU hwmon
    for hwmon_dir in sorted(_glob.glob("/sys/class/drm/card*/device/hwmon/hwmon*")):
        try:
            name_path = f"{hwmon_dir}/name"
            name = "GPU"
            if _glob.os.path.exists(name_path):
                with open(name_path) as fh:
                    name = fh.read().strip()
            temp_input = f"{hwmon_dir}/temp1_input"
            if not _glob.os.path.exists(temp_input):
                continue
            with open(temp_input) as fh:
                val = int(fh.read().strip())
            if val > 0:
                return GpuReading(
                    temperature=round(val / 1000.0, 1),
                    usage_percent=None,
                    name=name,
                )
        except (ValueError, OSError):
            continue

    # Approach 2: look in /sys/class/hwmon for GPU-related sensors
    for name_path in sorted(_glob.glob("/sys/class/hwmon/hwmon*/name")):
        try:
            hwmon_dir = name_path.rsplit("/", 1)[0]
            with open(name_path) as fh:
                name = fh.read().strip().lower()
            if name not in ("amdgpu", "radeon", "nouveau", "i915"):
                continue
            temp_input = f"{hwmon_dir}/temp1_input"
            if not _glob.os.path.exists(temp_input):
                continue
            with open(temp_input) as fh:
                val = int(fh.read().strip())
            if val > 0:
                return GpuReading(
                    temperature=round(val / 1000.0, 1),
                    usage_percent=None,
                    name=name.upper(),
                )
        except (ValueError, OSError):
            continue

    return None


def _read_ohm_gpu() -> GpuReading | None:
    """Read GPU temperature via Open Hardware Monitor WMI."""
    if not _IS_WINDOWS:
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
    """Return current GPU temperature and usage.

    Tries multiple sources in order of reliability:
    NVML → nvidia-smi → sysfs (Linux) → OHM (Windows).
    """
    reading = _read_nvml()
    if reading is not None:
        return reading

    reading = _read_nvidia_smi()
    if reading is not None:
        return reading

    reading = _read_sysfs_gpu()
    if reading is not None:
        return reading

    reading = _read_ohm_gpu()
    if reading is not None:
        return reading

    return GpuReading(temperature=None, usage_percent=None, name="Unknown GPU")
