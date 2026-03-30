"""Application bootstrap — wires all components together."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from systemommy.alerts.manager import AlertManager
from systemommy.config import AppConfig
from systemommy.constants import APP_NAME, APP_VERSION, ORG_NAME
from systemommy.hardware.history import TemperatureHistory
from systemommy.hardware.monitor import HardwareMonitor, HardwareSnapshot
from systemommy.overlay.widget import OverlayWidget
from systemommy.ui.main_window import MainWindow
from systemommy.ui.theme import GLOBAL_STYLESHEET
from systemommy.ui.tray import SystemTray

logger = logging.getLogger(__name__)

_LOG_DIR = Path.home() / ".systemommy"
_LOG_FILE = _LOG_DIR / "systemommy.log"


def _setup_logging() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        handlers.append(file_handler)
    except OSError:
        pass  # Non-fatal — continue with console only
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


class SystemommyApp:
    """Top-level application controller."""

    def __init__(self) -> None:
        _setup_logging()

        self._config = AppConfig.load()
        self._qt_app = QApplication(sys.argv)
        self._qt_app.setApplicationName(APP_NAME)
        self._qt_app.setApplicationVersion(APP_VERSION)
        self._qt_app.setOrganizationName(ORG_NAME)
        self._qt_app.setStyleSheet(GLOBAL_STYLESHEET)
        self._qt_app.setQuitOnLastWindowClosed(False)

        # Components
        self._history = TemperatureHistory()
        self._monitor = HardwareMonitor(
            interval_ms=self._config.overlay.update_interval_ms
        )
        self._alert_mgr = AlertManager(self._config)
        self._overlay = OverlayWidget(self._config)
        self._window = MainWindow(self._config, self._history)
        self._tray = SystemTray()

        self._connect_signals()

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        # Hardware → overlay + window + alerts
        self._monitor.reading_updated.connect(self._on_reading)

        # Alert → window status bar
        self._alert_mgr.alert_triggered.connect(self._window.show_alert_in_status)

        # Tray actions
        self._tray.action_toggle_overlay.triggered.connect(self._toggle_overlay)
        self._tray.action_settings.triggered.connect(self._show_settings)
        self._tray.action_quit.triggered.connect(self._quit)
        self._tray.activated.connect(self._on_tray_activated)

        # Config change → overlay refresh + monitor interval
        self._window.config_changed.connect(self._on_config_changed)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_reading(self, snapshot: HardwareSnapshot) -> None:
        self._history.record(
            cpu_temp=snapshot.cpu.temperature,
            gpu_temp=snapshot.gpu.temperature,
        )
        self._overlay.update_reading(snapshot)
        self._window.update_reading(snapshot)
        self._alert_mgr.evaluate(snapshot)
        self._window.update_correction_status(
            self._alert_mgr.corrector.is_cpu_corrected,
            self._alert_mgr.corrector.is_gpu_corrected,
        )

    def _toggle_overlay(self) -> None:
        self._config.overlay.enabled = not self._config.overlay.enabled
        self._overlay.setVisible(self._config.overlay.enabled)
        self._config.save()

    def _show_settings(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _quit(self) -> None:
        self._monitor.stop()
        self._alert_mgr.corrector.restore_all()
        self._config.save()
        self._qt_app.quit()

    def _on_tray_activated(self, reason: SystemTray.ActivationReason) -> None:
        if reason == SystemTray.ActivationReason.DoubleClick:
            self._show_settings()

    def _on_config_changed(self) -> None:
        self._overlay.apply_config()
        self._monitor.set_interval(self._config.overlay.update_interval_ms)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Start the event loop."""
        logger.info("Starting %s v%s", APP_NAME, APP_VERSION)

        # Show overlay if enabled
        if self._config.overlay.enabled:
            self._overlay.show()

        # Show main window unless start_minimized
        if not self._config.start_minimized:
            self._window.show()

        self._tray.show()
        self._monitor.start()

        return self._qt_app.exec()


def run_application() -> int:
    """Public entry point called from ``__main__``."""
    app = SystemommyApp()
    return app.run()
