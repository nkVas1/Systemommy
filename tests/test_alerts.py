"""Tests for AlertManager evaluation logic."""

from __future__ import annotations

import pytest

from systemommy.alerts.manager import AlertManager
from systemommy.config import AppConfig
from systemommy.hardware.cpu import CpuReading
from systemommy.hardware.gpu import GpuReading
from systemommy.hardware.monitor import HardwareSnapshot


def _snapshot(
    cpu_temp: float | None = 50.0,
    gpu_temp: float | None = 50.0,
) -> HardwareSnapshot:
    """Create a test hardware snapshot."""
    return HardwareSnapshot(
        cpu=CpuReading(temperature=cpu_temp, usage_percent=30.0),
        gpu=GpuReading(temperature=gpu_temp, usage_percent=40.0, name="Test GPU"),
    )


@pytest.mark.usefixtures("qtbot")
class TestAlertManagerEvaluate:
    """Verify alert triggering logic."""

    def test_no_alert_when_disabled(self) -> None:
        cfg = AppConfig()
        cfg.alerts.enabled = False
        mgr = AlertManager(cfg)
        signals: list[tuple[str, str]] = []
        mgr.alert_triggered.connect(lambda level, msg: signals.append((level, msg)))
        mgr.evaluate(_snapshot(cpu_temp=100.0))
        assert len(signals) == 0

    def test_no_alert_below_thresholds(self) -> None:
        cfg = AppConfig()
        mgr = AlertManager(cfg)
        signals: list[tuple[str, str]] = []
        mgr.alert_triggered.connect(lambda level, msg: signals.append((level, msg)))
        mgr.evaluate(_snapshot(cpu_temp=60.0, gpu_temp=60.0))
        assert len(signals) == 0

    def test_cpu_critical_triggers_alert(self) -> None:
        cfg = AppConfig()
        mgr = AlertManager(cfg)
        signals: list[tuple[str, str]] = []
        mgr.alert_triggered.connect(lambda level, msg: signals.append((level, msg)))
        mgr.evaluate(_snapshot(cpu_temp=95.0))
        assert len(signals) == 1
        assert signals[0][0] == "critical"
        assert "CPU" in signals[0][1]

    def test_gpu_warning_triggers_alert(self) -> None:
        cfg = AppConfig()
        mgr = AlertManager(cfg)
        signals: list[tuple[str, str]] = []
        mgr.alert_triggered.connect(lambda level, msg: signals.append((level, msg)))
        mgr.evaluate(_snapshot(cpu_temp=50.0, gpu_temp=85.0))
        assert len(signals) == 1
        assert signals[0][0] == "warning"
        assert "GPU" in signals[0][1]

    def test_cooldown_prevents_duplicate_alerts(self) -> None:
        cfg = AppConfig()
        cfg.alerts.cooldown_s = 60
        mgr = AlertManager(cfg)
        signals: list[tuple[str, str]] = []
        mgr.alert_triggered.connect(lambda level, msg: signals.append((level, msg)))
        # First call triggers
        mgr.evaluate(_snapshot(cpu_temp=95.0))
        # Second call within cooldown should not trigger
        mgr.evaluate(_snapshot(cpu_temp=95.0))
        assert len(signals) == 1

    def test_none_temps_produce_no_alert(self) -> None:
        cfg = AppConfig()
        mgr = AlertManager(cfg)
        signals: list[tuple[str, str]] = []
        mgr.alert_triggered.connect(lambda level, msg: signals.append((level, msg)))
        mgr.evaluate(_snapshot(cpu_temp=None, gpu_temp=None))
        assert len(signals) == 0


class TestAlertSettingsValidation:
    """Verify threshold validation in AlertSettings."""

    def test_warning_clamped_below_critical(self) -> None:
        from systemommy.config import AlertSettings

        s = AlertSettings(cpu_warning=95, cpu_critical=90)
        assert s.cpu_warning < s.cpu_critical

    def test_gpu_warning_clamped_below_critical(self) -> None:
        from systemommy.config import AlertSettings

        s = AlertSettings(gpu_warning=92, gpu_critical=90)
        assert s.gpu_warning < s.gpu_critical
