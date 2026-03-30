"""Main settings window — tabbed UI for configuring Systemommy."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPaintEvent, QColor, QPen, QPainterPath
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
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
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_GREEN,
    COLOR_GOLD,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
)
from systemommy.hardware.history import TemperatureHistory, TemperaturePoint
from systemommy.hardware.info import CpuInfo, GpuInfo, detect_cpu_info, detect_gpu_info
from systemommy.hardware.monitor import HardwareSnapshot

logger = logging.getLogger(__name__)


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
            logger.debug("Hardware info detection failed in dashboard.", exc_info=True)

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

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(10)
        layout.setContentsMargins(6, 6, 6, 6)

        group = QGroupBox("» Thermal Correction")
        group_lay = QVBoxLayout(group)
        group_lay.setSpacing(8)

        info = QLabel(
            "When enabled, Systemommy can automatically reduce CPU/GPU "
            "performance to lower dangerous temperatures. All changes "
            "are reversible and restored when temps return to normal.\n\n"
            "• CPU: lowers the maximum processor boost clock (via "
            "Windows power settings) — base clock is not affected.\n"
            "• GPU: lowers the firmware power limit (via NVML) — the "
            "GPU throttles safely within manufacturer-allowed range.\n\n"
            "These measures cannot damage hardware — they use the same "
            "mechanisms that Windows and GPU firmware use internally."
        )
        info.setStyleSheet(f"color: {COLOR_PURPLE}; font-size: 11px;")
        info.setWordWrap(True)
        group_lay.addWidget(info)

        self.auto_cb = QCheckBox("Enable automatic thermal correction")
        self.auto_cb.setToolTip(
            "When checked, Systemommy will automatically apply safe throttling\n"
            "if temperatures reach the critical threshold. All changes are\n"
            "reversed when temperatures return to normal."
        )
        self.auto_cb.setChecked(config.thermal.auto_correct_enabled)
        group_lay.addWidget(self.auto_cb)

        self.ask_cb = QCheckBox("Ask permission before applying")
        self.ask_cb.setToolTip(
            "When checked, a confirmation dialog will appear before any\n"
            "thermal correction is applied. If unchecked, corrections\n"
            "are applied automatically when temperatures are critical."
        )
        self.ask_cb.setChecked(config.thermal.ask_before_correct)
        group_lay.addWidget(self.ask_cb)

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

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

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


# ------------------------------------------------------------------
# Temperature graph widget (pure QPainter — no external dependencies)
# ------------------------------------------------------------------


class _TemperatureGraphWidget(QWidget):
    """Custom widget that draws a temperature-over-time line graph."""

    _MARGIN_LEFT = 48
    _MARGIN_RIGHT = 12
    _MARGIN_TOP = 10
    _MARGIN_BOTTOM = 28

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[TemperaturePoint] = []
        self._show_cpu = True
        self._show_gpu = True
        self._min_temp = 20.0
        self._max_temp = 100.0
        self.setMinimumHeight(180)

    def set_data(
        self,
        points: list[TemperaturePoint],
        *,
        show_cpu: bool = True,
        show_gpu: bool = True,
    ) -> None:
        """Update the graph data and trigger a repaint."""
        self._points = points
        self._show_cpu = show_cpu
        self._show_gpu = show_gpu
        self._recalc_range(points)
        self.update()

    def _recalc_range(self, points: list[TemperaturePoint]) -> None:
        temps: list[float] = []
        for p in points:
            if self._show_cpu and p.cpu_temp is not None:
                temps.append(p.cpu_temp)
            if self._show_gpu and p.gpu_temp is not None:
                temps.append(p.gpu_temp)
        if temps:
            self._min_temp = max(0.0, min(temps) - 5)
            self._max_temp = max(temps) + 5
        else:
            self._min_temp, self._max_temp = 20.0, 100.0
        if self._max_temp - self._min_temp < 10:
            self._max_temp = self._min_temp + 10

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        ml, mr, mt, mb = (
            self._MARGIN_LEFT,
            self._MARGIN_RIGHT,
            self._MARGIN_TOP,
            self._MARGIN_BOTTOM,
        )
        gw = w - ml - mr  # graph area width
        gh = h - mt - mb  # graph area height

        # Background
        painter.fillRect(self.rect(), QColor(COLOR_BG_PANEL))

        if gw < 10 or gh < 10:
            painter.end()
            return

        # Grid
        grid_pen = QPen(QColor(COLOR_BORDER))
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        temp_range = self._max_temp - self._min_temp
        step = max(5, int(temp_range / 5))
        t = int(self._min_temp / step) * step
        while t <= self._max_temp:
            y = mt + gh - (t - self._min_temp) / temp_range * gh
            painter.drawLine(ml, int(y), ml + gw, int(y))
            t += step

        # Y-axis labels
        label_pen = QPen(QColor(COLOR_TEXT_DIM))
        painter.setPen(label_pen)
        painter.setFont(QFont("Consolas", 8))
        t = int(self._min_temp / step) * step
        while t <= self._max_temp:
            y = mt + gh - (t - self._min_temp) / temp_range * gh
            painter.drawText(2, int(y) - 6, ml - 6, 14, Qt.AlignmentFlag.AlignRight, f"{t}°")
            t += step

        # X-axis time labels
        points = self._points
        if len(points) >= 2:
            t_start = points[0].timestamp
            t_end = points[-1].timestamp
            t_span = t_end - t_start
            if t_span > 0:
                # Draw 4–5 time labels
                for i in range(5):
                    frac = i / 4.0
                    x = ml + int(frac * gw)
                    ts = t_start + frac * t_span
                    label = time.strftime("%H:%M", time.localtime(ts))
                    painter.drawText(
                        x - 20, h - mb + 4, 40, 14,
                        Qt.AlignmentFlag.AlignCenter, label,
                    )

        # Draw temperature lines
        if self._show_cpu:
            self._draw_line(painter, points, "cpu", QColor(COLOR_GREEN), gw, gh, ml, mt)
        if self._show_gpu:
            self._draw_line(painter, points, "gpu", QColor(COLOR_PURPLE), gw, gh, ml, mt)

        # Legend
        lx = ml + 6
        ly = mt + 4
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        if self._show_cpu:
            painter.setPen(QPen(QColor(COLOR_GREEN)))
            painter.drawText(lx, ly, 80, 14, Qt.AlignmentFlag.AlignLeft, "— CPU")
            lx += 56
        if self._show_gpu:
            painter.setPen(QPen(QColor(COLOR_PURPLE)))
            painter.drawText(lx, ly, 80, 14, Qt.AlignmentFlag.AlignLeft, "— GPU")

        painter.end()

    def _draw_line(
        self,
        painter: QPainter,
        points: list[TemperaturePoint],
        sensor: str,
        color: QColor,
        gw: int,
        gh: int,
        ml: int,
        mt: int,
    ) -> None:
        if len(points) < 2:
            return
        t_start = points[0].timestamp
        t_end = points[-1].timestamp
        t_span = t_end - t_start
        if t_span <= 0:
            return

        temp_range = self._max_temp - self._min_temp
        pen = QPen(color, 2)
        painter.setPen(pen)

        path = QPainterPath()
        first = True
        for p in points:
            temp = p.cpu_temp if sensor == "cpu" else p.gpu_temp
            if temp is None:
                continue
            x = ml + (p.timestamp - t_start) / t_span * gw
            y = mt + gh - (temp - self._min_temp) / temp_range * gh
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)
        painter.drawPath(path)


class _MetricsTab(_ScanlineWidget):
    """Temperature history graphs with recent / full-session views."""

    def __init__(self, config: AppConfig, history: TemperatureHistory) -> None:
        super().__init__()
        self._config = config
        self._history = history

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 8, 8, 8)

        # Controls row
        ctrl_row = QHBoxLayout()

        ctrl_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Recent (15 min)", 15)
        self.mode_combo.addItem("Recent (30 min)", 30)
        self.mode_combo.addItem("Full session", 0)
        self.mode_combo.currentIndexChanged.connect(self._refresh_graph)
        ctrl_row.addWidget(self.mode_combo)
        ctrl_row.addStretch()

        self.show_cpu_cb = QCheckBox("CPU")
        self.show_cpu_cb.setChecked(True)
        self.show_cpu_cb.toggled.connect(self._refresh_graph)
        ctrl_row.addWidget(self.show_cpu_cb)

        self.show_gpu_cb = QCheckBox("GPU")
        self.show_gpu_cb.setChecked(True)
        self.show_gpu_cb.toggled.connect(self._refresh_graph)
        ctrl_row.addWidget(self.show_gpu_cb)

        layout.addLayout(ctrl_row)

        # Graph widget
        graph_group = QGroupBox("» Temperature Graph")
        graph_lay = QVBoxLayout(graph_group)
        graph_lay.setContentsMargins(6, 16, 6, 6)
        self.graph = _TemperatureGraphWidget()
        graph_lay.addWidget(self.graph)
        layout.addWidget(graph_group, stretch=1)

        # Stats group
        stats_group = QGroupBox("» Session Statistics")
        stats_lay = QFormLayout(stats_group)

        self.cpu_min_label = QLabel("—")
        self.cpu_max_label = QLabel("—")
        self.cpu_avg_label = QLabel("—")
        self.gpu_min_label = QLabel("—")
        self.gpu_max_label = QLabel("—")
        self.gpu_avg_label = QLabel("—")
        self.points_label = QLabel("0")

        for lbl in (
            self.cpu_min_label, self.cpu_max_label, self.cpu_avg_label,
            self.gpu_min_label, self.gpu_max_label, self.gpu_avg_label,
            self.points_label,
        ):
            lbl.setStyleSheet(f"color: {COLOR_TEXT_DIM};")

        stats_lay.addRow("CPU min / max / avg:", self._stat_row(
            self.cpu_min_label, self.cpu_max_label, self.cpu_avg_label,
        ))
        stats_lay.addRow("GPU min / max / avg:", self._stat_row(
            self.gpu_min_label, self.gpu_max_label, self.gpu_avg_label,
        ))
        stats_lay.addRow("Data points:", self.points_label)

        layout.addWidget(stats_group)

    @staticmethod
    def _stat_row(lbl_min: QLabel, lbl_max: QLabel, lbl_avg: QLabel) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(lbl_min)
        row.addWidget(QLabel("/"))
        row.addWidget(lbl_max)
        row.addWidget(QLabel("/"))
        row.addWidget(lbl_avg)
        row.addStretch()
        return w

    def update_graph(self) -> None:
        """Re-render the graph and stats from current history data."""
        self._refresh_graph()

    def _refresh_graph(self) -> None:
        minutes = self.mode_combo.currentData()
        if minutes and minutes > 0:
            points = self._history.recent(float(minutes))
        else:
            points = self._history.full_session()

        show_cpu = self.show_cpu_cb.isChecked()
        show_gpu = self.show_gpu_cb.isChecked()

        self.graph.set_data(points, show_cpu=show_cpu, show_gpu=show_gpu)
        self._update_stats(points, show_cpu, show_gpu)

    def _update_stats(
        self,
        points: list[TemperaturePoint],
        show_cpu: bool,
        show_gpu: bool,
    ) -> None:
        self.points_label.setText(str(len(points)))

        cpu_temps = [p.cpu_temp for p in points if p.cpu_temp is not None]
        gpu_temps = [p.gpu_temp for p in points if p.gpu_temp is not None]

        if cpu_temps and show_cpu:
            self.cpu_min_label.setText(f"{min(cpu_temps):.1f} °C")
            self.cpu_max_label.setText(f"{max(cpu_temps):.1f} °C")
            self.cpu_avg_label.setText(f"{sum(cpu_temps) / len(cpu_temps):.1f} °C")
        else:
            self.cpu_min_label.setText("—")
            self.cpu_max_label.setText("—")
            self.cpu_avg_label.setText("—")

        if gpu_temps and show_gpu:
            self.gpu_min_label.setText(f"{min(gpu_temps):.1f} °C")
            self.gpu_max_label.setText(f"{max(gpu_temps):.1f} °C")
            self.gpu_avg_label.setText(f"{sum(gpu_temps) / len(gpu_temps):.1f} °C")
        else:
            self.gpu_min_label.setText("—")
            self.gpu_max_label.setText("—")
            self.gpu_avg_label.setText("—")


class MainWindow(QMainWindow):
    """Main settings window with tabbed interface."""

    config_changed = Signal()

    def __init__(self, config: AppConfig, history: TemperatureHistory | None = None) -> None:
        super().__init__()
        self._config = config
        self._history = history or TemperatureHistory()

        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.setMinimumSize(480, 560)
        self.resize(500, 620)

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
        self.metrics_tab = _MetricsTab(config, self._history)

        self.tabs.addTab(self.dashboard_tab, "⌂ Dashboard")
        self.tabs.addTab(self.overlay_tab, "◉ Overlay")
        self.tabs.addTab(self.alerts_tab, "⊘ Alerts")
        self.tabs.addTab(self.thermal_tab, "♨ Thermal")
        self.tabs.addTab(self.metrics_tab, "▤ Metrics")

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
        # Update metrics graph (only when tab is visible for performance)
        if self.tabs.currentWidget() is self.metrics_tab:
            self.metrics_tab.update_graph()

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
