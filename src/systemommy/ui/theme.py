"""Skeuomorphic hacker / terminal theme — QSS stylesheet and helpers."""

from systemommy.constants import (
    COLOR_BG_DARK,
    COLOR_BG_PANEL,
    COLOR_BG_WIDGET,
    COLOR_BORDER,
    COLOR_GOLD,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
)

GLOBAL_STYLESHEET = f"""
/* ── Base ─────────────────────────────────────────────────── */
QWidget {{
    background-color: {COLOR_BG_DARK};
    color: {COLOR_TEXT};
    font-family: "Consolas", "Courier New", monospace;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {COLOR_BG_DARK};
}}

/* ── Group boxes ──────────────────────────────────────────── */
QGroupBox {{
    background-color: {COLOR_BG_PANEL};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 14px 10px 10px 10px;
    font-weight: bold;
    color: {COLOR_GREEN};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {COLOR_GREEN};
}}

/* ── Labels ───────────────────────────────────────────────── */
QLabel {{
    background: transparent;
    color: {COLOR_TEXT};
}}
QLabel[role="heading"] {{
    font-size: 18px;
    font-weight: bold;
    color: {COLOR_GREEN};
}}
QLabel[role="status"] {{
    font-size: 11px;
    color: {COLOR_TEXT_DIM};
}}

/* ── Buttons ──────────────────────────────────────────────── */
QPushButton {{
    background-color: {COLOR_BG_WIDGET};
    color: {COLOR_GREEN};
    border: 1px solid {COLOR_GREEN};
    border-radius: 4px;
    padding: 6px 18px;
    font-weight: bold;
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: rgba(57, 255, 20, 0.10);
    border-color: {COLOR_GREEN};
}}
QPushButton:pressed {{
    background-color: rgba(57, 255, 20, 0.20);
}}
QPushButton:disabled {{
    color: {COLOR_TEXT_DIM};
    border-color: {COLOR_BORDER};
}}
QPushButton[role="danger"] {{
    color: {COLOR_RED};
    border-color: {COLOR_RED};
}}
QPushButton[role="danger"]:hover {{
    background-color: rgba(255, 45, 45, 0.10);
}}

/* ── Check boxes ──────────────────────────────────────────── */
QCheckBox {{
    spacing: 8px;
    color: {COLOR_TEXT};
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {COLOR_GREEN};
    border-radius: 3px;
    background: {COLOR_BG_WIDGET};
}}
QCheckBox::indicator:checked {{
    background: {COLOR_GREEN};
    border-color: {COLOR_GREEN};
}}

/* ── Spin boxes ───────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background-color: {COLOR_BG_WIDGET};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 24px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {COLOR_GREEN};
}}

/* ── Combo boxes ──────────────────────────────────────────── */
QComboBox {{
    background-color: {COLOR_BG_WIDGET};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 24px;
}}
QComboBox:focus {{
    border-color: {COLOR_GREEN};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background: {COLOR_BG_PANEL};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: rgba(57, 255, 20, 0.15);
    selection-color: {COLOR_GREEN};
}}

/* ── Sliders ──────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    height: 4px;
    background: {COLOR_BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    background: {COLOR_GREEN};
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {COLOR_GREEN};
    border-radius: 2px;
}}

/* ── Tab widget ───────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    background: {COLOR_BG_PANEL};
    top: -1px;
}}
QTabBar::tab {{
    background: {COLOR_BG_DARK};
    color: {COLOR_TEXT_DIM};
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 20px;
    margin-right: 2px;
    font-weight: bold;
}}
QTabBar::tab:selected {{
    background: {COLOR_BG_PANEL};
    color: {COLOR_GREEN};
    border-color: {COLOR_GREEN};
}}
QTabBar::tab:hover:!selected {{
    color: {COLOR_TEXT};
}}

/* ── Scroll area ──────────────────────────────────────────── */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    width: 8px;
    background: {COLOR_BG_DARK};
}}
QScrollBar::handle:vertical {{
    background: {COLOR_BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* ── Status bar ───────────────────────────────────────────── */
QStatusBar {{
    background: {COLOR_BG_PANEL};
    color: {COLOR_TEXT_DIM};
    border-top: 1px solid {COLOR_BORDER};
    font-size: 11px;
}}

/* ── Tooltips ─────────────────────────────────────────────── */
QToolTip {{
    background: {COLOR_BG_PANEL};
    color: {COLOR_GREEN};
    border: 1px solid {COLOR_GREEN};
    padding: 4px 8px;
    font-size: 12px;
}}

/* ── Accent colour roles ──────────────────────────────────── */
QLabel[accent="green"]  {{ color: {COLOR_GREEN}; }}
QLabel[accent="red"]    {{ color: {COLOR_RED}; }}
QLabel[accent="gold"]   {{ color: {COLOR_GOLD}; }}
QLabel[accent="purple"] {{ color: {COLOR_PURPLE}; }}
"""
