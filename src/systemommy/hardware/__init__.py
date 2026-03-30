"""Hardware monitoring sub-package."""

from systemommy.hardware.cpu import CpuReading
from systemommy.hardware.gpu import GpuReading
from systemommy.hardware.info import (
    CpuInfo,
    GpuInfo,
    RecommendedThresholds,
    detect_cpu_info,
    detect_gpu_info,
    recommended_thresholds,
)
from systemommy.hardware.monitor import HardwareMonitor, HardwareSnapshot
from systemommy.hardware.thermal import ThermalCorrector

__all__ = [
    "CpuInfo",
    "CpuReading",
    "GpuInfo",
    "GpuReading",
    "HardwareMonitor",
    "HardwareSnapshot",
    "RecommendedThresholds",
    "ThermalCorrector",
    "detect_cpu_info",
    "detect_gpu_info",
    "recommended_thresholds",
]
