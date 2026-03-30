"""Tests for hardware info detection module."""

from __future__ import annotations

from unittest.mock import patch

from systemommy.hardware.info import (
    CpuInfo,
    GpuInfo,
    RecommendedThresholds,
    _estimate_gpu_max_temp,
    _estimate_tjmax,
    detect_cpu_info,
    detect_gpu_info,
    recommended_thresholds,
)


class TestEstimateTjmax:
    """Verify TjMax estimation for different CPU families."""

    def test_intel_core_i7(self) -> None:
        assert _estimate_tjmax("Intel(R) Core(TM) i7-12700K") == 100

    def test_intel_core_i9_13th(self) -> None:
        assert _estimate_tjmax("Intel(R) Core(TM) i9-13900K") == 100

    def test_intel_xeon(self) -> None:
        assert _estimate_tjmax("Intel(R) Xeon(R) E-2288G") == 95

    def test_amd_ryzen_7(self) -> None:
        assert _estimate_tjmax("AMD Ryzen 7 5800X") == 95

    def test_amd_ryzen_9(self) -> None:
        assert _estimate_tjmax("AMD Ryzen 9 7950X") == 95

    def test_amd_threadripper(self) -> None:
        assert _estimate_tjmax("AMD Ryzen Threadripper 3970X") == 95

    def test_unknown_cpu(self) -> None:
        assert _estimate_tjmax("Some Unknown Processor") == 100

    def test_case_insensitive(self) -> None:
        assert _estimate_tjmax("INTEL CORE I7-12700K") == 100
        assert _estimate_tjmax("amd ryzen 5 5600x") == 95


class TestEstimateGpuMaxTemp:
    """Verify GPU max temperature estimation."""

    def test_nvidia_rtx_3060(self) -> None:
        assert _estimate_gpu_max_temp("NVIDIA GeForce RTX 3060 Ti") == 93

    def test_nvidia_rtx_4090(self) -> None:
        assert _estimate_gpu_max_temp("NVIDIA GeForce RTX 4090") == 90

    def test_amd_rx_7900(self) -> None:
        assert _estimate_gpu_max_temp("AMD Radeon RX 7900 XTX") == 100

    def test_unknown_gpu(self) -> None:
        assert _estimate_gpu_max_temp("Unknown GPU") == 93


class TestDetectCpuInfo:
    """Verify CPU info detection."""

    def test_returns_cpuinfo_dataclass(self) -> None:
        info = detect_cpu_info()
        assert isinstance(info, CpuInfo)

    def test_has_valid_core_counts(self) -> None:
        info = detect_cpu_info()
        assert info.physical_cores >= 1
        assert info.logical_cores >= info.physical_cores

    def test_model_is_nonempty(self) -> None:
        info = detect_cpu_info()
        assert len(info.model) > 0

    def test_tjmax_is_reasonable(self) -> None:
        info = detect_cpu_info()
        assert 80 <= info.tjmax <= 120


class TestDetectGpuInfo:
    """Verify GPU info detection."""

    def test_returns_gpuinfo_dataclass(self) -> None:
        info = detect_gpu_info()
        assert isinstance(info, GpuInfo)

    def test_name_is_nonempty(self) -> None:
        info = detect_gpu_info()
        assert len(info.name) > 0

    def test_max_temp_is_reasonable(self) -> None:
        info = detect_gpu_info()
        assert 70 <= info.max_temp <= 120


class TestRecommendedThresholds:
    """Verify threshold recommendation logic."""

    def test_returns_dataclass(self) -> None:
        rec = recommended_thresholds()
        assert isinstance(rec, RecommendedThresholds)

    def test_warning_below_critical(self) -> None:
        rec = recommended_thresholds()
        assert rec.cpu_warning < rec.cpu_critical
        assert rec.gpu_warning < rec.gpu_critical

    def test_thresholds_have_minimum_floor(self) -> None:
        rec = recommended_thresholds()
        assert rec.cpu_warning >= 60
        assert rec.cpu_critical >= 70
        assert rec.gpu_warning >= 60
        assert rec.gpu_critical >= 70

    def test_with_explicit_hardware(self) -> None:
        cpu = CpuInfo(
            model="Test CPU",
            physical_cores=4,
            logical_cores=8,
            max_frequency_mhz=3600.0,
            tjmax=100,
        )
        gpu = GpuInfo(name="Test GPU", max_temp=93)
        rec = recommended_thresholds(cpu_info=cpu, gpu_info=gpu)
        # CPU critical = TjMax - 8 = 92
        assert rec.cpu_critical == 92
        # GPU critical = max_temp - 5 = 88
        assert rec.gpu_critical == 88
        # Warnings should be below criticals
        assert rec.cpu_warning < rec.cpu_critical
        assert rec.gpu_warning < rec.gpu_critical

    def test_with_low_tjmax_clamped_to_floor(self) -> None:
        cpu = CpuInfo(
            model="Cool CPU",
            physical_cores=2,
            logical_cores=4,
            max_frequency_mhz=2000.0,
            tjmax=70,  # very low TjMax
        )
        gpu = GpuInfo(name="Cool GPU", max_temp=70)
        rec = recommended_thresholds(cpu_info=cpu, gpu_info=gpu)
        assert rec.cpu_critical >= 70
        assert rec.gpu_critical >= 70
        assert rec.cpu_warning >= 60
        assert rec.gpu_warning >= 60
