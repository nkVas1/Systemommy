"""Tests for constants module."""

from systemommy.constants import (
    CPU_TEMP_CRITICAL,
    CPU_TEMP_WARNING,
    GPU_TEMP_CRITICAL,
    GPU_TEMP_WARNING,
    COLOR_GREEN,
    COLOR_RED,
)


def test_cpu_thresholds_ordering() -> None:
    assert CPU_TEMP_WARNING < CPU_TEMP_CRITICAL


def test_gpu_thresholds_ordering() -> None:
    assert GPU_TEMP_WARNING < GPU_TEMP_CRITICAL


def test_colors_are_hex() -> None:
    assert COLOR_GREEN.startswith("#")
    assert COLOR_RED.startswith("#")
