"""Transparent always-on-top temperature overlay widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from systemommy.config import AppConfig
from systemommy.constants import (
    COLOR_GOLD,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_TEXT_DIM,
)
from systemommy.hardware.monitor import HardwareSnapshot


def _temp_color(temp: float | None, warning: int, critical: int) -> str:
    """Return a hex colour based on temperature severity."""
    if temp is None:
        return COLOR_TEXT_DIM
    if temp >= critical:
        return COLOR_RED
    if temp >= warning:
        return COLOR_GOLD
    return COLOR_GREEN


class OverlayWidget(QWidget):
    """Semi-transparent, frameless overlay that stays on top of all windows."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__(None)
        self._config = config

        # Window flags: frameless, always-on-top, tool (no taskbar entry),
        # transparent for input (clicks pass through)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)

        self._cpu_label = QLabel("CPU: — °C")
        self._gpu_label = QLabel("GPU: — °C")

        for label in (self._cpu_label, self._gpu_label):
            label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(label)

        self._apply_style()
        self._apply_position()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_reading(self, snapshot: HardwareSnapshot) -> None:
        """Refresh displayed values from a hardware snapshot."""
        ov = self._config.overlay
        alert = self._config.alerts

        if ov.show_cpu:
            cpu_t = snapshot.cpu.temperature
            cpu_color = _temp_color(cpu_t, alert.cpu_warning, alert.cpu_critical)
            cpu_text = f"{cpu_t:.0f}" if cpu_t is not None else "—"
            self._cpu_label.setText(f"CPU: {cpu_text} °C")
            self._cpu_label.setStyleSheet(
                f"color: {cpu_color}; background: transparent;"
            )
            self._cpu_label.setVisible(True)
        else:
            self._cpu_label.setVisible(False)

        if ov.show_gpu:
            gpu_t = snapshot.gpu.temperature
            gpu_color = _temp_color(gpu_t, alert.gpu_warning, alert.gpu_critical)
            gpu_text = f"{gpu_t:.0f}" if gpu_t is not None else "—"
            self._gpu_label.setText(f"GPU: {gpu_text} °C")
            self._gpu_label.setStyleSheet(
                f"color: {gpu_color}; background: transparent;"
            )
            self._gpu_label.setVisible(True)
        else:
            self._gpu_label.setVisible(False)

        self.adjustSize()

    def apply_config(self) -> None:
        """Re-apply visual settings from config (call after config change)."""
        self._apply_style()
        self._apply_position()
        self.setVisible(self._config.overlay.enabled)

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """Draw semi-transparent background with subtle CRT scanline effect."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        bg = painter.brush()
        from PySide6.QtGui import QColor

        bg_color = QColor(10, 10, 10, int(255 * self._config.overlay.opacity))
        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 4, 4)

        # Scanline overlay
        pen_color = QColor(255, 255, 255, 8)
        painter.setPen(pen_color)
        y = 0
        while y < self.height():
            painter.drawLine(0, y, self.width(), y)
            y += 3

        painter.end()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_style(self) -> None:
        font = QFont("Consolas", self._config.overlay.font_size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        for label in (self._cpu_label, self._gpu_label):
            label.setFont(font)
            label.setStyleSheet(
                f"color: {COLOR_GREEN}; background: transparent;"
            )

    def _apply_position(self) -> None:
        ov = self._config.overlay
        self.move(ov.position_x, ov.position_y)
