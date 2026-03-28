"""Tests for configuration persistence."""

from __future__ import annotations

import json
from pathlib import Path

from systemommy.config import AlertSettings, AppConfig, OverlaySettings, ThermalSettings


class TestAppConfigDefaults:
    """Verify default configuration values."""

    def test_overlay_defaults(self) -> None:
        cfg = AppConfig()
        assert cfg.overlay.enabled is True
        assert cfg.overlay.show_cpu is True
        assert cfg.overlay.show_gpu is True
        assert cfg.overlay.font_size == 12
        assert 0 < cfg.overlay.opacity <= 1.0

    def test_alert_defaults(self) -> None:
        cfg = AppConfig()
        assert cfg.alerts.enabled is True
        assert cfg.alerts.sound_enabled is True
        assert cfg.alerts.cpu_critical >= 90

    def test_thermal_defaults(self) -> None:
        cfg = AppConfig()
        assert cfg.thermal.auto_correct_enabled is False
        assert cfg.thermal.ask_before_correct is True


class TestAppConfigPersistence:
    """Round-trip save/load."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        cfg = AppConfig()
        cfg.overlay.font_size = 20
        cfg.alerts.cpu_critical = 95
        cfg.thermal.auto_correct_enabled = True
        cfg.save(config_dir=tmp_path)

        loaded = AppConfig.load(config_dir=tmp_path)
        assert loaded.overlay.font_size == 20
        assert loaded.alerts.cpu_critical == 95
        assert loaded.thermal.auto_correct_enabled is True

    def test_load_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        loaded = AppConfig.load(config_dir=tmp_path)
        assert loaded.overlay.enabled is True
        assert loaded.alerts.cpu_critical == AppConfig().alerts.cpu_critical

    def test_load_corrupt_file_returns_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json{{{", encoding="utf-8")
        loaded = AppConfig.load(config_dir=tmp_path)
        assert loaded.overlay.enabled is True

    def test_saved_file_is_valid_json(self, tmp_path: Path) -> None:
        cfg = AppConfig()
        cfg.save(config_dir=tmp_path)
        raw = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert "overlay" in raw
        assert "alerts" in raw
        assert "thermal" in raw


class TestOverlaySettings:
    def test_defaults(self) -> None:
        s = OverlaySettings()
        assert s.enabled is True
        assert s.update_interval_ms >= 500


class TestAlertSettings:
    def test_warning_less_than_critical(self) -> None:
        s = AlertSettings()
        assert s.cpu_warning < s.cpu_critical
        assert s.gpu_warning < s.gpu_critical


class TestThermalSettings:
    def test_defaults(self) -> None:
        s = ThermalSettings()
        assert s.auto_correct_enabled is False
        assert s.ask_before_correct is True
