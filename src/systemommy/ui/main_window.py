"""Main settings window — tabbed UI for configuring Systemommy."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPaintEvent, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSlider,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from systemommy.config import AppConfig
from systemommy.constants import (
    APP_NAME,
    APP_VERSION,
    COLOR_BG_DARK,
    COLOR_GREEN,
    COLOR_GOLD,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_TEXT_DIM,
)
from systemommy.hardware.info import CpuInfo, GpuInfo, detect_cpu_info, detect_gpu_info
from systemommy.hardware.monitor import HardwareSnapshot


class _ScanlineWidget(QWidget):
    """Base widget that draws a subtle CRT scanline effect over its background."""

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        pen_color = QColor(255, 255, 255, 6)
        painter.setPen(pen_color)
        y = 0
        while y < self.height():
            painter.drawLine(0, y, self.width(), y)
            y += 3
        painter.end()


class _DashboardTab(_ScanlineWidget):
    """Live readings dashboard."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # Title
        title = QLabel(f"[ {APP_NAME} v{APP_VERSION} ]")
        title.setProperty("role", "heading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Hardware info group
        hw_group = QGroupBox("» Hardware")
        hw_lay = QFormLayout(hw_group)
        self._cpu_info: CpuInfo | None = None
        self._gpu_info: GpuInfo | None = None
        try:
            self._cpu_info = detect_cpu_info()
            self._gpu_info = detect_gpu_info()
        except Exception:  # noqa: BLE001
            pass

        cpu_model = self._cpu_info.model if self._cpu_info else "Detecting…"
        cpu_cores = (
            f"{self._cpu_info.physical_cores}C / {self._cpu_info.logical_cores}T"
            if self._cpu_info
            else "—"
        )
        cpu_freq = (
            f"{self._cpu_info.max_frequency_mhz:.0f} MHz"
            if self._cpu_info and self._cpu_info.max_frequency_mhz > 0
            else "—"
        )
        gpu_name_text = self._gpu_info.name if self._gpu_info else "Detecting…"

        self.hw_cpu_model_label = QLabel(cpu_model)
        self.hw_cpu_model_label.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        self.hw_cpu_model_label.setWordWrap(True)
        hw_lay.addRow("CPU:", self.hw_cpu_model_label)

        self.hw_cpu_cores_label = QLabel(cpu_cores)
        self.hw_cpu_cores_label.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        hw_lay.addRow("Cores:", self.hw_cpu_cores_label)

        self.hw_cpu_freq_label = QLabel(cpu_freq)
        self.hw_cpu_freq_label.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        hw_lay.addRow("Max freq:", self.hw_cpu_freq_label)

        self.hw_gpu_name_label = QLabel(gpu_name_text)
        self.hw_gpu_name_label.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        self.hw_gpu_name_label.setWordWrap(True)
        hw_lay.addRow("GPU:", self.hw_gpu_name_label)

        layout.addWidget(hw_group)

        # CPU group
        cpu_group = QGroupBox("» CPU")
        cpu_lay = QFormLayout(cpu_group)
        self.cpu_temp_label = QLabel("— °C")
        self.cpu_temp_label.setFont(QFont("Consolas", 22, QFont.Weight.Bold))
        self.cpu_usage_label = QLabel("— %")
        cpu_lay.addRow("Temperature:", self.cpu_temp_label)
        cpu_lay.addRow("Usage:", self.cpu_usage_label)
        layout.addWidget(cpu_group)

        # GPU group
        gpu_group = QGroupBox("» GPU")
        gpu_lay = QFormLayout(gpu_group)
        self.gpu_temp_label = QLabel("— °C")
        self.gpu_temp_label.setFont(QFont("Consolas", 22, QFont.Weight.Bold))
        self.gpu_usage_label = QLabel("— %")
        self.gpu_name_label = QLabel("—")
        self.gpu_name_label.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        gpu_lay.addRow("Temperature:", self.gpu_temp_label)
        gpu_lay.addRow("Usage:", self.gpu_usage_label)
        gpu_lay.addRow("Device:", self.gpu_name_label)
        layout.addWidget(gpu_group)

        # Status
        self.status_label = QLabel("Monitoring active")
        self.status_label.setProperty("role", "status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        layout.addStretch()

    def update_reading(self, snapshot: HardwareSnapshot) -> None:
        """Refresh dashboard values."""
        alert = self._config.alerts

        # CPU
        cpu_t = snapshot.cpu.temperature
        if cpu_t is not None:
            self.cpu_temp_label.setText(f"{cpu_t:.1f} °C")
            if cpu_t >= alert.cpu_critical:
                self.cpu_temp_label.setStyleSheet(f"color: {COLOR_RED};")
            elif cpu_t >= alert.cpu_warning:
                self.cpu_temp_label.setStyleSheet(f"color: {COLOR_GOLD};")
            else:
                self.cpu_temp_label.setStyleSheet(f"color: {COLOR_GREEN};")
        else:
            self.cpu_temp_label.setText("N/A")
            self.cpu_temp_label.setStyleSheet(f"color: {COLOR_TEXT_DIM};")

        self.cpu_usage_label.setText(f"{snapshot.cpu.usage_percent:.0f} %")

        # GPU
        gpu_t = snapshot.gpu.temperature
        if gpu_t is not None:
            self.gpu_temp_label.setText(f"{gpu_t:.1f} °C")
            if gpu_t >= alert.gpu_critical:
                self.gpu_temp_label.setStyleSheet(f"color: {COLOR_RED};")
            elif gpu_t >= alert.gpu_warning:
                self.gpu_temp_label.setStyleSheet(f"color: {COLOR_GOLD};")
            else:
                self.gpu_temp_label.setStyleSheet(f"color: {COLOR_GREEN};")
        else:
            self.gpu_temp_label.setText("N/A")
            self.gpu_temp_label.setStyleSheet(f"color: {COLOR_TEXT_DIM};")

        gpu_usage = snapshot.gpu.usage_percent
        self.gpu_usage_label.setText(
            f"{gpu_usage:.0f} %" if gpu_usage is not None else "N/A"
        )
        self.gpu_name_label.setText(snapshot.gpu.name)


class _OverlayTab(_ScanlineWidget):
    """Overlay settings."""

    changed = Signal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        group = QGroupBox("» Overlay Settings")
        form = QFormLayout(group)

        self.enabled_cb = QCheckBox("Enable overlay")
        self.enabled_cb.setChecked(config.overlay.enabled)
        form.addRow(self.enabled_cb)

        self.show_cpu_cb = QCheckBox("Show CPU temperature")
        self.show_cpu_cb.setChecked(config.overlay.show_cpu)
        form.addRow(self.show_cpu_cb)

        self.show_gpu_cb = QCheckBox("Show GPU temperature")
        self.show_gpu_cb.setChecked(config.overlay.show_gpu)
        form.addRow(self.show_gpu_cb)

        # Opacity slider
        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(int(config.overlay.opacity * 100))
        self.opacity_value_label = QLabel(f"{int(config.overlay.opacity * 100)}%")
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_value_label.setText(f"{v}%")
        )
        opacity_row.addWidget(self.opacity_slider)
        opacity_row.addWidget(self.opacity_value_label)
        form.addRow("Opacity:", opacity_row)

        # Font size
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 32)
        self.font_spin.setValue(config.overlay.font_size)
        form.addRow("Font size:", self.font_spin)

        # Update interval
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(500, 10000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setValue(config.overlay.update_interval_ms)
        form.addRow("Update interval:", self.interval_spin)

        # Position
        pos_row = QHBoxLayout()
        self.pos_x_spin = QSpinBox()
        self.pos_x_spin.setRange(0, 9999)
        self.pos_x_spin.setValue(config.overlay.position_x)
        self.pos_y_spin = QSpinBox()
        self.pos_y_spin.setRange(0, 9999)
        self.pos_y_spin.setValue(config.overlay.position_y)
        pos_row.addWidget(QLabel("X:"))
        pos_row.addWidget(self.pos_x_spin)
        pos_row.addWidget(QLabel("Y:"))
        pos_row.addWidget(self.pos_y_spin)
        form.addRow("Position:", pos_row)

        layout.addWidget(group)
        layout.addStretch()

        # Wire up signals
        for widget in (
            self.enabled_cb,
            self.show_cpu_cb,
            self.show_gpu_cb,
        ):
            widget.toggled.connect(self._on_changed)
        for widget in (
            self.opacity_slider,
            self.font_spin,
            self.interval_spin,
            self.pos_x_spin,
            self.pos_y_spin,
        ):
            widget.valueChanged.connect(self._on_changed)

    def apply_to_config(self) -> None:
        """Write current widget values into the config object."""
        ov = self._config.overlay
        ov.enabled = self.enabled_cb.isChecked()
        ov.show_cpu = self.show_cpu_cb.isChecked()
        ov.show_gpu = self.show_gpu_cb.isChecked()
        ov.opacity = self.opacity_slider.value() / 100.0
        ov.font_size = self.font_spin.value()
        ov.update_interval_ms = self.interval_spin.value()
        ov.position_x = self.pos_x_spin.value()
        ov.position_y = self.pos_y_spin.value()

    def _on_changed(self) -> None:
        self.apply_to_config()
        self.changed.emit()


class _AlertsTab(_ScanlineWidget):
    """Alert threshold settings."""

    changed = Signal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        group = QGroupBox("» Alert Thresholds")
        form = QFormLayout(group)

        self.enabled_cb = QCheckBox("Enable alerts")
        self.enabled_cb.setToolTip(
            "Enable temperature monitoring alerts.\n"
            "Alerts are shown in the status bar and optionally play a sound."
        )
        self.enabled_cb.setChecked(config.alerts.enabled)
        form.addRow(self.enabled_cb)

        self.sound_cb = QCheckBox("Play alert sound")
        self.sound_cb.setToolTip(
            "Play a system alert sound when temperature thresholds\n"
            "are exceeded. Limited to a few plays per alert cycle."
        )
        self.sound_cb.setChecked(config.alerts.sound_enabled)
        form.addRow(self.sound_cb)

        # CPU thresholds
        self.cpu_warn_spin = QSpinBox()
        self.cpu_warn_spin.setRange(50, 110)
        self.cpu_warn_spin.setSuffix(" °C")
        self.cpu_warn_spin.setValue(config.alerts.cpu_warning)
        self.cpu_warn_spin.setToolTip(
            "Temperature at which a CPU warning alert is triggered.\n"
            "Should be below the critical threshold."
        )
        form.addRow("CPU warning:", self.cpu_warn_spin)

        self.cpu_crit_spin = QSpinBox()
        self.cpu_crit_spin.setRange(50, 120)
        self.cpu_crit_spin.setSuffix(" °C")
        self.cpu_crit_spin.setValue(config.alerts.cpu_critical)
        self.cpu_crit_spin.setToolTip(
            "Temperature at which a CPU critical alert is triggered.\n"
            "Thermal correction (if enabled) activates at this level."
        )
        form.addRow("CPU critical:", self.cpu_crit_spin)

        # GPU thresholds
        self.gpu_warn_spin = QSpinBox()
        self.gpu_warn_spin.setRange(50, 110)
        self.gpu_warn_spin.setSuffix(" °C")
        self.gpu_warn_spin.setValue(config.alerts.gpu_warning)
        self.gpu_warn_spin.setToolTip(
            "Temperature at which a GPU warning alert is triggered.\n"
            "Should be below the critical threshold."
        )
        form.addRow("GPU warning:", self.gpu_warn_spin)

        self.gpu_crit_spin = QSpinBox()
        self.gpu_crit_spin.setRange(50, 120)
        self.gpu_crit_spin.setSuffix(" °C")
        self.gpu_crit_spin.setValue(config.alerts.gpu_critical)
        self.gpu_crit_spin.setToolTip(
            "Temperature at which a GPU critical alert is triggered.\n"
            "Thermal correction (if enabled) activates at this level."
        )
        form.addRow("GPU critical:", self.gpu_crit_spin)

        # Cooldown
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(10, 600)
        self.cooldown_spin.setSuffix(" s")
        self.cooldown_spin.setValue(config.alerts.cooldown_s)
        self.cooldown_spin.setToolTip(
            "Minimum time between consecutive alerts (in seconds).\n"
            "Prevents alert spam when temperatures are consistently high."
        )
        form.addRow("Alert cooldown:", self.cooldown_spin)

        layout.addWidget(group)
        layout.addStretch()

        for widget in (self.enabled_cb, self.sound_cb):
            widget.toggled.connect(self._on_changed)
        for widget in (
            self.cpu_warn_spin,
            self.cpu_crit_spin,
            self.gpu_warn_spin,
            self.gpu_crit_spin,
            self.cooldown_spin,
        ):
            widget.valueChanged.connect(self._on_changed)

    def apply_to_config(self) -> None:
        """Write current widget values into the config object."""
        a = self._config.alerts
        a.enabled = self.enabled_cb.isChecked()
        a.sound_enabled = self.sound_cb.isChecked()
        a.cpu_warning = self.cpu_warn_spin.value()
        a.cpu_critical = self.cpu_crit_spin.value()
        a.gpu_warning = self.gpu_warn_spin.value()
        a.gpu_critical = self.gpu_crit_spin.value()
        a.cooldown_s = self.cooldown_spin.value()

    def _on_changed(self) -> None:
        self.apply_to_config()
        self.changed.emit()


class _ThermalTab(_ScanlineWidget):
    """Thermal correction settings."""

    changed = Signal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        group = QGroupBox("» Thermal Correction")
        form = QFormLayout(group)

        info = QLabel(
            "When enabled, Systemommy can automatically reduce CPU/GPU\n"
            "performance to lower dangerous temperatures. All changes\n"
            "are reversible and restored when temps return to normal.\n\n"
            "• CPU: lowers the maximum processor boost clock (via\n"
            "  Windows power settings) — base clock is not affected.\n"
            "• GPU: lowers the firmware power limit (via NVML) — the\n"
            "  GPU throttles safely within manufacturer-allowed range.\n\n"
            "These measures cannot damage hardware — they use the same\n"
            "mechanisms that Windows and GPU firmware use internally."
        )
        info.setStyleSheet(f"color: {COLOR_PURPLE}; font-size: 11px;")
        info.setWordWrap(True)
        form.addRow(info)

        self.auto_cb = QCheckBox("Enable automatic thermal correction")
        self.auto_cb.setToolTip(
            "When checked, Systemommy will automatically apply safe throttling\n"
            "if temperatures reach the critical threshold. All changes are\n"
            "reversed when temperatures return to normal."
        )
        self.auto_cb.setChecked(config.thermal.auto_correct_enabled)
        form.addRow(self.auto_cb)

        self.ask_cb = QCheckBox("Ask permission before applying")
        self.ask_cb.setToolTip(
            "When checked, a confirmation dialog will appear before any\n"
            "thermal correction is applied. If unchecked, corrections\n"
            "are applied automatically when temperatures are critical."
        )
        self.ask_cb.setChecked(config.thermal.ask_before_correct)
        form.addRow(self.ask_cb)

        layout.addWidget(group)

        # Safety info group
        safety_group = QGroupBox("» Safety Information")
        safety_lay = QVBoxLayout(safety_group)
        safety_label = QLabel(
            "✓ All corrections stay within manufacturer-specified limits.\n"
            "✓ The OS and hardware thermal protections remain active.\n"
            "✓ Corrections are automatically reversed when temps normalise.\n"
            "✓ No voltage, BIOS, or permanent hardware changes are made.\n"
            "✓ If the app closes unexpectedly, changes persist only until\n"
            "   the next reboot or manual restoration."
        )
        safety_label.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 11px;")
        safety_label.setWordWrap(True)
        safety_lay.addWidget(safety_label)
        layout.addWidget(safety_group)

        # Status group
        status_group = QGroupBox("» Correction Status")
        status_lay = QFormLayout(status_group)
        self.cpu_status_label = QLabel("Normal")
        self.cpu_status_label.setStyleSheet(f"color: {COLOR_GREEN};")
        self.gpu_status_label = QLabel("Normal")
        self.gpu_status_label.setStyleSheet(f"color: {COLOR_GREEN};")
        status_lay.addRow("CPU:", self.cpu_status_label)
        status_lay.addRow("GPU:", self.gpu_status_label)
        layout.addWidget(status_group)

        layout.addStretch()

        self.auto_cb.toggled.connect(self._on_changed)
        self.ask_cb.toggled.connect(self._on_changed)

    def apply_to_config(self) -> None:
        a = self._config.thermal
        a.auto_correct_enabled = self.auto_cb.isChecked()
        a.ask_before_correct = self.ask_cb.isChecked()

    def update_correction_status(
        self, cpu_corrected: bool, gpu_corrected: bool
    ) -> None:
        if cpu_corrected:
            self.cpu_status_label.setText("⚡ Throttled")
            self.cpu_status_label.setStyleSheet(f"color: {COLOR_GOLD};")
        else:
            self.cpu_status_label.setText("Normal")
            self.cpu_status_label.setStyleSheet(f"color: {COLOR_GREEN};")
        if gpu_corrected:
            self.gpu_status_label.setText("⚡ Throttled")
            self.gpu_status_label.setStyleSheet(f"color: {COLOR_GOLD};")
        else:
            self.gpu_status_label.setText("Normal")
            self.gpu_status_label.setStyleSheet(f"color: {COLOR_GREEN};")

    def _on_changed(self) -> None:
        self.apply_to_config()
        self.changed.emit()


class MainWindow(QMainWindow):
    """Main settings window with tabbed interface."""

    config_changed = Signal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config

        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.setMinimumSize(460, 520)
        self.resize(480, 580)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 6)

        # Tab widget
        self.tabs = QTabWidget()
        self.dashboard_tab = _DashboardTab(config)
        self.overlay_tab = _OverlayTab(config)
        self.alerts_tab = _AlertsTab(config)
        self.thermal_tab = _ThermalTab(config)

        self.tabs.addTab(self.dashboard_tab, "⌂ Dashboard")
        self.tabs.addTab(self.overlay_tab, "◉ Overlay")
        self.tabs.addTab(self.alerts_tab, "⚠ Alerts")
        self.tabs.addTab(self.thermal_tab, "♨ Thermal")

        main_layout.addWidget(self.tabs)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Connect settings-change signals
        self.overlay_tab.changed.connect(self._on_settings_changed)
        self.alerts_tab.changed.connect(self._on_settings_changed)
        self.thermal_tab.changed.connect(self._on_settings_changed)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def update_reading(self, snapshot: HardwareSnapshot) -> None:
        """Forward hardware reading to relevant tabs."""
        self.dashboard_tab.update_reading(snapshot)

    def update_correction_status(
        self, cpu_corrected: bool, gpu_corrected: bool
    ) -> None:
        self.thermal_tab.update_correction_status(cpu_corrected, gpu_corrected)

    def show_alert_in_status(self, level: str, message: str) -> None:
        self.status_bar.showMessage(message, 10000)

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        """Hide to tray instead of quitting."""
        event.ignore()
        self.hide()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_settings_changed(self) -> None:
        self._config.save()
        self.config_changed.emit()
