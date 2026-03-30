"""Hardware information detection.

Reads CPU and GPU specifications and estimates safe temperature thresholds
based on the detected hardware model.  All detection is best-effort:
functions return sensible defaults when information cannot be determined.
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from dataclasses import dataclass

import psutil

from systemommy.constants import (
    CPU_TEMP_CRITICAL,
    CPU_TEMP_WARNING,
    GPU_TEMP_CRITICAL,
    GPU_TEMP_WARNING,
    THRESHOLD_MINIMUM_GAP,
)

logger = logging.getLogger(__name__)

_IS_LINUX = platform.system() == "Linux"
_IS_WINDOWS = platform.system() == "Windows"

# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------


@dataclass(frozen=True)
class CpuInfo:
    """Detected CPU specifications."""

    model: str  # e.g. "Intel Core i7-12700K"
    physical_cores: int
    logical_cores: int
    max_frequency_mhz: float  # 0.0 if unknown
    tjmax: int  # estimated maximum junction temperature (°C)


@dataclass(frozen=True)
class GpuInfo:
    """Detected GPU specifications."""

    name: str  # e.g. "NVIDIA GeForce RTX 3060 Ti"
    max_temp: int  # estimated maximum safe temperature (°C)


@dataclass(frozen=True)
class RecommendedThresholds:
    """Hardware-aware temperature thresholds."""

    cpu_warning: int
    cpu_critical: int
    gpu_warning: int
    gpu_critical: int


# ------------------------------------------------------------------
# CPU detection helpers
# ------------------------------------------------------------------


def _cpu_model_name() -> str:
    """Return the CPU model string, e.g. 'Intel Core i7-12700K'."""
    # Linux: /proc/cpuinfo
    if _IS_LINUX:
        try:
            with open("/proc/cpuinfo") as fh:
                for line in fh:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass

    # Windows: platform.processor() or WMIC
    if _IS_WINDOWS:
        try:
            result = subprocess.run(
                ["wmic", "cpu", "get", "Name", "/value"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for line in result.stdout.splitlines():
                if line.startswith("Name="):
                    return line.split("=", 1)[1].strip()
        except Exception:  # noqa: BLE001
            pass

    fallback = platform.processor()
    return fallback if fallback else "Unknown CPU"


def _estimate_tjmax(model: str) -> int:
    """Estimate TjMax (°C) from the CPU model string.

    Returns a conservative estimate — slightly below the manufacturer's
    rated junction temperature.  Falls back to 100 °C if unknown.
    """
    model_lower = model.lower()

    # Intel — most desktop chips are 100 °C; high-end HEDT is 90-100 °C;
    # mobile parts can be up to 105 °C.
    if "intel" in model_lower or "core" in model_lower:
        if any(tag in model_lower for tag in ("i9-14", "i9-13", "i9-12",
                                               "i7-14", "i7-13", "i7-12")):
            return 100
        if any(tag in model_lower for tag in ("i9-", "i7-", "i5-", "i3-")):
            return 100
        if "xeon" in model_lower:
            return 95
        if "celeron" in model_lower or "pentium" in model_lower:
            return 100
        return 100

    # AMD — Ryzen desktop parts are typically 95 °C (Zen 3/4)
    if "amd" in model_lower or "ryzen" in model_lower:
        if "ryzen 9" in model_lower:
            return 95
        if "ryzen 7" in model_lower:
            return 95
        if "ryzen 5" in model_lower:
            return 95
        if "threadripper" in model_lower:
            return 95
        if "epyc" in model_lower:
            return 96
        return 95

    # Unknown — use a safe default
    return 100


# ------------------------------------------------------------------
# GPU detection helpers
# ------------------------------------------------------------------


def _gpu_name() -> str:
    """Return the GPU name string."""
    # Try nvidia-smi first (both platforms)
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            name = result.stdout.strip().splitlines()[0].strip()
            if name:
                return name
    except Exception:  # noqa: BLE001
        pass

    # Windows: WMIC
    if _IS_WINDOWS:
        try:
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "Name", "/value"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for line in result.stdout.splitlines():
                if line.startswith("Name="):
                    return line.split("=", 1)[1].strip()
        except Exception:  # noqa: BLE001
            pass

    # Linux: /sys/class/drm
    if _IS_LINUX:
        try:
            import glob as _glob

            for uevent_path in sorted(
                _glob.glob("/sys/class/drm/card*/device/uevent")
            ):
                with open(uevent_path) as fh:
                    for line in fh:
                        if line.startswith("PCI_ID="):
                            return f"GPU ({line.strip()})"
        except OSError:
            pass

    return "Unknown GPU"


def _estimate_gpu_max_temp(name: str) -> int:
    """Estimate the maximum safe operating temperature for the GPU.

    Returns a conservative value — 5-10 °C below the absolute limit.
    Defaults to 93 °C if the GPU family cannot be determined.
    """
    name_lower = name.lower()

    # NVIDIA — most GeForce cards max out at 83-93 °C
    if "nvidia" in name_lower or "geforce" in name_lower or "rtx" in name_lower:
        if "rtx 40" in name_lower or "rtx 50" in name_lower:
            return 90
        if "rtx 30" in name_lower:
            return 93
        if "rtx 20" in name_lower:
            return 89
        if "gtx 16" in name_lower:
            return 97
        if "gtx 10" in name_lower:
            return 94
        return 93

    # AMD — Radeon RX series
    if "amd" in name_lower or "radeon" in name_lower:
        if "rx 7" in name_lower:
            return 100
        if "rx 6" in name_lower:
            return 110
        return 100

    # Intel — Arc
    if "intel" in name_lower or "arc" in name_lower:
        return 100

    return 93


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def detect_cpu_info() -> CpuInfo:
    """Detect CPU specifications.

    Returns a :class:`CpuInfo` dataclass with model name, core counts,
    maximum frequency, and estimated TjMax.
    """
    model = _cpu_model_name()
    physical = psutil.cpu_count(logical=False) or 1
    logical = psutil.cpu_count(logical=True) or physical
    freq = psutil.cpu_freq()
    max_freq = freq.max if freq and freq.max > 0 else (freq.current if freq else 0.0)
    tjmax = _estimate_tjmax(model)

    return CpuInfo(
        model=model,
        physical_cores=physical,
        logical_cores=logical,
        max_frequency_mhz=max_freq,
        tjmax=tjmax,
    )


def detect_gpu_info() -> GpuInfo:
    """Detect GPU specifications.

    Returns a :class:`GpuInfo` dataclass with the device name and
    estimated maximum safe temperature.
    """
    name = _gpu_name()
    max_temp = _estimate_gpu_max_temp(name)
    return GpuInfo(name=name, max_temp=max_temp)


def recommended_thresholds(
    cpu_info: CpuInfo | None = None,
    gpu_info: GpuInfo | None = None,
) -> RecommendedThresholds:
    """Compute recommended warning/critical thresholds for the detected hardware.

    If hardware info is not provided, it will be auto-detected.
    Critical thresholds are set 5-8 °C below the hardware maximum, and
    warning thresholds are ``THRESHOLD_MINIMUM_GAP`` °C below critical.
    """
    if cpu_info is None:
        cpu_info = detect_cpu_info()
    if gpu_info is None:
        gpu_info = detect_gpu_info()

    # CPU: critical = TjMax - 8, warning = critical - gap
    cpu_critical = cpu_info.tjmax - 8
    cpu_warning = cpu_critical - THRESHOLD_MINIMUM_GAP

    # GPU: critical = max_temp - 5, warning = critical - gap
    gpu_critical = gpu_info.max_temp - 5
    gpu_warning = gpu_critical - THRESHOLD_MINIMUM_GAP

    return RecommendedThresholds(
        cpu_warning=max(cpu_warning, 60),   # floor at 60 °C
        cpu_critical=max(cpu_critical, 70),  # floor at 70 °C
        gpu_warning=max(gpu_warning, 60),
        gpu_critical=max(gpu_critical, 70),
    )
