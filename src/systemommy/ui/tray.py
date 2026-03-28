"""System tray icon and context menu."""

from __future__ import annotations

from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from systemommy.constants import COLOR_GREEN


def _create_tray_icon() -> QIcon:
    """Programmatically create a small green "S" icon for the tray."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Green circle background
    painter.setBrush(QColor(COLOR_GREEN))
    painter.setPen(QColor(0, 0, 0, 180))
    painter.drawEllipse(2, 2, size - 4, size - 4)

    # "S" letter
    font = QFont("Consolas", 36, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor(10, 10, 10))
    painter.drawText(pixmap.rect(), 0x0084, "S")  # AlignCenter

    painter.end()
    return QIcon(pixmap)


class SystemTray(QSystemTrayIcon):
    """Tray icon with show/hide overlay, open settings, and quit actions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(_create_tray_icon(), parent)
        self.setToolTip("Systemommy — Temperature Monitor")

        self._menu = QMenu()
        self._menu.setStyleSheet(
            "QMenu { background: #141414; color: #d0d0d0; border: 1px solid #2a2a2a; }"
            "QMenu::item:selected { background: rgba(57,255,20,0.15); color: #39ff14; }"
        )

        self.action_toggle_overlay = QAction("Toggle Overlay", self)
        self.action_settings = QAction("Settings", self)
        self.action_quit = QAction("Quit", self)

        self._menu.addAction(self.action_toggle_overlay)
        self._menu.addAction(self.action_settings)
        self._menu.addSeparator()
        self._menu.addAction(self.action_quit)

        self.setContextMenu(self._menu)
