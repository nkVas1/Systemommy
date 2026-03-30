"""Tests for CPU and GPU temperature reader fallback chains."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import os
import tempfile

from systemommy.hardware.cpu import (
    CpuReading,
    _read_temperature_psutil,
    _read_temperature_sysfs,
    _read_temperature_ohm_ps,
    _read_temperature_lhwm_ps,
    read_cpu,
)
from systemommy.hardware.gpu import (
    GpuReading,
    _read_nvidia_smi,
    _read_sysfs_gpu,
    _read_ohm_gpu_ps,
    _read_lhwm_gpu_ps,
    read_gpu,
)


class TestCpuSysfsFallback:
    """Verify sysfs temperature reading on Linux."""

    def test_sysfs_returns_none_on_non_linux(self) -> None:
        with patch("systemommy.hardware.cpu._IS_LINUX", False):
            assert _read_temperature_sysfs() is None

    def test_sysfs_reads_hwmon(self, tmp_path) -> None:
        """Simulate a coretemp hwmon device."""
        hwmon_dir = tmp_path / "hwmon0"
        hwmon_dir.mkdir()
        (hwmon_dir / "name").write_text("coretemp\n")
        (hwmon_dir / "temp1_input").write_text("65000\n")  # 65.0 °C
        (hwmon_dir / "temp2_input").write_text("72000\n")  # 72.0 °C

        with (
            patch("systemommy.hardware.cpu._IS_LINUX", True),
            patch(
                "systemommy.hardware.cpu._glob.glob",
                side_effect=lambda pattern: (
                    [str(hwmon_dir / "name")]
                    if "name" in pattern
                    else sorted(str(p) for p in hwmon_dir.glob("temp*_input"))
                    if "temp*_input" in pattern
                    else []
                ),
            ),
        ):
            temp = _read_temperature_sysfs()
            assert temp is not None
            assert temp == 72.0

    def test_sysfs_reads_thermal_zone(self, tmp_path) -> None:
        """Simulate a thermal_zone device."""
        zone_dir = tmp_path / "thermal_zone0"
        zone_dir.mkdir()
        (zone_dir / "temp").write_text("58000\n")  # 58.0 °C

        with (
            patch("systemommy.hardware.cpu._IS_LINUX", True),
            patch(
                "systemommy.hardware.cpu._glob.glob",
                side_effect=lambda pattern: (
                    []
                    if "hwmon" in pattern
                    else [str(zone_dir / "temp")]
                ),
            ),
        ):
            temp = _read_temperature_sysfs()
            assert temp is not None
            assert temp == 58.0


class TestGpuNvidiaSmi:
    """Verify nvidia-smi CLI fallback."""

    def test_parses_valid_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "72, 45, NVIDIA GeForce RTX 3060 Ti\n"

        with patch("systemommy.hardware.gpu.subprocess.run", return_value=mock_result):
            reading = _read_nvidia_smi()
            assert reading is not None
            assert reading.temperature == 72.0
            assert reading.usage_percent == 45.0
            assert "RTX 3060 Ti" in reading.name

    def test_returns_none_on_failure(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("systemommy.hardware.gpu.subprocess.run", return_value=mock_result):
            assert _read_nvidia_smi() is None

    def test_returns_none_on_exception(self) -> None:
        with patch(
            "systemommy.hardware.gpu.subprocess.run",
            side_effect=FileNotFoundError("nvidia-smi not found"),
        ):
            assert _read_nvidia_smi() is None


class TestGpuSysfsFallback:
    """Verify sysfs GPU temperature reading."""

    def test_returns_none_on_non_linux(self) -> None:
        with patch("systemommy.hardware.gpu._IS_LINUX", False):
            assert _read_sysfs_gpu() is None


class TestReadCpuFallbackChain:
    """Verify the read_cpu() fallback chain."""

    def test_returns_cpu_reading(self) -> None:
        reading = read_cpu()
        assert isinstance(reading, CpuReading)
        assert isinstance(reading.usage_percent, float)

    def test_temperature_may_be_none(self) -> None:
        """On systems without sensors, temperature is None — not an error."""
        reading = read_cpu()
        assert reading.temperature is None or isinstance(reading.temperature, float)


class TestReadGpuFallbackChain:
    """Verify the read_gpu() fallback chain."""

    def test_returns_gpu_reading(self) -> None:
        reading = read_gpu()
        assert isinstance(reading, GpuReading)
        assert isinstance(reading.name, str)

    def test_temperature_may_be_none(self) -> None:
        """On systems without GPU sensors, temperature is None — not an error."""
        reading = read_gpu()
        assert reading.temperature is None or isinstance(reading.temperature, float)


class TestOhmPsFallback:
    """Verify PowerShell-based OHM CPU temperature reading."""

    def test_returns_none_on_non_windows(self) -> None:
        with patch("systemommy.hardware.cpu._IS_WINDOWS", False):
            assert _read_temperature_ohm_ps() is None

    def test_parses_valid_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "72.5\n68.3\n"

        with (
            patch("systemommy.hardware.cpu._IS_WINDOWS", True),
            patch("systemommy.hardware.cpu.subprocess.run", return_value=mock_result),
        ):
            temp = _read_temperature_ohm_ps()
            assert temp is not None
            assert temp == 72.5

    def test_returns_none_on_failure(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("systemommy.hardware.cpu._IS_WINDOWS", True),
            patch("systemommy.hardware.cpu.subprocess.run", return_value=mock_result),
        ):
            assert _read_temperature_ohm_ps() is None


class TestLhwmPsFallback:
    """Verify PowerShell-based LHWM CPU temperature reading."""

    def test_returns_none_on_non_windows(self) -> None:
        with patch("systemommy.hardware.cpu._IS_WINDOWS", False):
            assert _read_temperature_lhwm_ps() is None

    def test_parses_valid_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "85.0\n"

        with (
            patch("systemommy.hardware.cpu._IS_WINDOWS", True),
            patch("systemommy.hardware.cpu.subprocess.run", return_value=mock_result),
        ):
            temp = _read_temperature_lhwm_ps()
            assert temp is not None
            assert temp == 85.0


class TestGpuOhmPsFallback:
    """Verify PowerShell-based OHM GPU temperature reading."""

    def test_returns_none_on_non_windows(self) -> None:
        with patch("systemommy.hardware.gpu._IS_WINDOWS", False):
            assert _read_ohm_gpu_ps() is None

    def test_parses_valid_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "65.0\n"

        with (
            patch("systemommy.hardware.gpu._IS_WINDOWS", True),
            patch("systemommy.hardware.gpu.subprocess.run", return_value=mock_result),
        ):
            reading = _read_ohm_gpu_ps()
            assert reading is not None
            assert reading.temperature == 65.0
            assert reading.name == "GPU (OHM)"

    def test_returns_none_on_failure(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("systemommy.hardware.gpu._IS_WINDOWS", True),
            patch("systemommy.hardware.gpu.subprocess.run", return_value=mock_result),
        ):
            assert _read_ohm_gpu_ps() is None


class TestGpuLhwmPsFallback:
    """Verify PowerShell-based LHWM GPU temperature reading."""

    def test_returns_none_on_non_windows(self) -> None:
        with patch("systemommy.hardware.gpu._IS_WINDOWS", False):
            assert _read_lhwm_gpu_ps() is None

    def test_parses_valid_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "78.5\n"

        with (
            patch("systemommy.hardware.gpu._IS_WINDOWS", True),
            patch("systemommy.hardware.gpu.subprocess.run", return_value=mock_result),
        ):
            reading = _read_lhwm_gpu_ps()
            assert reading is not None
            assert reading.temperature == 78.5
            assert reading.name == "GPU (LHWM)"
