"""Temperature alert manager — warnings, sounds, thermal correction prompts."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from systemommy.config import AppConfig
from systemommy.hardware.monitor import HardwareSnapshot
from systemommy.hardware.thermal import ThermalCorrector

logger = logging.getLogger(__name__)


def _play_alert_sound() -> None:
    """Play a short alert beep using the platform default mechanism."""
    try:
        import winsound  # type: ignore[import-untyped]

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:  # noqa: BLE001
        # Fallback: Qt application beep
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app:
                app.beep()
        except Exception:  # noqa: BLE001
            pass


class AlertManager(QObject):
    """Evaluates hardware snapshots and fires alerts when thresholds are exceeded."""

    alert_triggered = Signal(str, str)  # (level, message)

    def __init__(self, config: AppConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._corrector = ThermalCorrector()
        self._last_alert_time: float = 0.0
        self._sound_play_count: int = 0
        self._correction_prompted: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, snapshot: HardwareSnapshot) -> None:
        """Check snapshot against thresholds and act accordingly."""
        if not self._config.alerts.enabled:
            return

        now = time.monotonic()
        alert_cfg = self._config.alerts

        cpu_temp = snapshot.cpu.temperature
        gpu_temp = snapshot.gpu.temperature

        # --- Critical CPU ---
        if cpu_temp is not None and cpu_temp >= alert_cfg.cpu_critical:
            self._fire_alert(
                now,
                "critical",
                f"⚠ CPU CRITICAL: {cpu_temp:.0f} °C (threshold {alert_cfg.cpu_critical} °C)",
            )
            self._maybe_correct_cpu(cpu_temp)
            return

        # --- Critical GPU ---
        if gpu_temp is not None and gpu_temp >= alert_cfg.gpu_critical:
            self._fire_alert(
                now,
                "critical",
                f"⚠ GPU CRITICAL: {gpu_temp:.0f} °C (threshold {alert_cfg.gpu_critical} °C)",
            )
            self._maybe_correct_gpu(gpu_temp)
            return

        # --- Warning CPU ---
        if cpu_temp is not None and cpu_temp >= alert_cfg.cpu_warning:
            self._fire_alert(
                now,
                "warning",
                f"CPU WARNING: {cpu_temp:.0f} °C (threshold {alert_cfg.cpu_warning} °C)",
            )
            return

        # --- Warning GPU ---
        if gpu_temp is not None and gpu_temp >= alert_cfg.gpu_warning:
            self._fire_alert(
                now,
                "warning",
                f"GPU WARNING: {gpu_temp:.0f} °C (threshold {alert_cfg.gpu_warning} °C)",
            )
            return

        # Temperatures normal — reset counters and restore if corrected
        self._sound_play_count = 0
        self._correction_prompted = False
        if self._corrector.is_cpu_corrected or self._corrector.is_gpu_corrected:
            self._corrector.restore_all()
            self.alert_triggered.emit(
                "info", "Temperatures normal — performance settings restored."
            )

    @property
    def corrector(self) -> ThermalCorrector:
        return self._corrector

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fire_alert(self, now: float, level: str, message: str) -> None:
        cooldown = self._config.alerts.cooldown_s
        if now - self._last_alert_time < cooldown:
            return
        self._last_alert_time = now

        logger.warning(message)
        self.alert_triggered.emit(level, message)

        if self._config.alerts.sound_enabled and self._sound_play_count < 2:
            _play_alert_sound()
            self._sound_play_count += 1

    def _maybe_correct_cpu(self, temp: float) -> None:
        if not self._config.thermal.auto_correct_enabled:
            return
        if self._corrector.is_cpu_corrected:
            return
        if self._config.thermal.ask_before_correct and not self._correction_prompted:
            self._correction_prompted = True
            reply = QMessageBox.question(
                None,
                "Systemommy — Thermal Correction",
                (
                    f"CPU temperature is critically high ({temp:.0f} °C).\n\n"
                    "Reduce CPU performance to lower temperature?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._corrector.correct_cpu()
        self.alert_triggered.emit(
            "info", "CPU thermal correction applied — max frequency reduced."
        )

    def _maybe_correct_gpu(self, temp: float) -> None:
        if not self._config.thermal.auto_correct_enabled:
            return
        if self._corrector.is_gpu_corrected:
            return
        if self._config.thermal.ask_before_correct and not self._correction_prompted:
            self._correction_prompted = True
            reply = QMessageBox.question(
                None,
                "Systemommy — Thermal Correction",
                (
                    f"GPU temperature is critically high ({temp:.0f} °C).\n\n"
                    "Reduce GPU power limit to lower temperature?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._corrector.correct_gpu()
        self.alert_triggered.emit(
            "info", "GPU thermal correction applied — power limit reduced."
        )
