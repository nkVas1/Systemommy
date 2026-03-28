"""Tests for thermal corrector data structures."""

from systemommy.hardware.thermal import ThermalCorrector


class TestThermalCorrector:
    def test_initial_state(self) -> None:
        tc = ThermalCorrector()
        assert tc.is_cpu_corrected is False
        assert tc.is_gpu_corrected is False

    def test_restore_noop_when_not_corrected(self) -> None:
        tc = ThermalCorrector()
        assert tc.restore_cpu() is True
        assert tc.restore_gpu() is True
