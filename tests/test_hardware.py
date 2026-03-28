"""Tests for hardware monitoring data structures."""

from __future__ import annotations

from systemommy.hardware.cpu import CpuReading
from systemommy.hardware.gpu import GpuReading


class TestCpuReading:
    def test_creation_with_temperature(self) -> None:
        r = CpuReading(temperature=65.3, usage_percent=42.0)
        assert r.temperature == 65.3
        assert r.usage_percent == 42.0

    def test_creation_with_none_temperature(self) -> None:
        r = CpuReading(temperature=None, usage_percent=0.0)
        assert r.temperature is None

    def test_frozen(self) -> None:
        r = CpuReading(temperature=50.0, usage_percent=10.0)
        try:
            r.temperature = 60.0  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass


class TestGpuReading:
    def test_creation(self) -> None:
        r = GpuReading(temperature=72.0, usage_percent=88.0, name="RTX 3060 Ti")
        assert r.temperature == 72.0
        assert r.name == "RTX 3060 Ti"

    def test_unknown_gpu(self) -> None:
        r = GpuReading(temperature=None, usage_percent=None, name="Unknown GPU")
        assert r.temperature is None
        assert r.name == "Unknown GPU"
