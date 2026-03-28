"""
CryptoPenetratorXL — Dark Theme Stylesheet (QSS)

Professional dark theme inspired by TigerTrade, TradingView,
and modern trading terminals.
"""

DARK_THEME = """
/* ====== Global ====== */
QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-family: "Segoe UI", "Consolas", sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #0d1117;
}

/* ====== Menu bar ====== */
QMenuBar {
    background-color: #161b22;
    border-bottom: 1px solid #30363d;
    padding: 2px;
}
QMenuBar::item {
    padding: 6px 12px;
    border-radius: 4px;
}
QMenuBar::item:selected {
    background-color: #21262d;
}
QMenu {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #1f6feb;
}

/* ====== Tab widget ====== */
QTabWidget::pane {
    border: 1px solid #30363d;
    border-radius: 4px;
    background-color: #0d1117;
}
QTabBar::tab {
    background-color: #161b22;
    color: #8b949e;
    padding: 8px 18px;
    border: 1px solid #30363d;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #0d1117;
    color: #58a6ff;
    border-bottom: 2px solid #58a6ff;
}
QTabBar::tab:hover {
    color: #c9d1d9;
    background-color: #21262d;
}

/* ====== Group box ====== */
QGroupBox {
    border: 1px solid #30363d;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #58a6ff;
}

/* ====== Push buttons ====== */
QPushButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
    min-height: 20px;
}
QPushButton:hover {
    background-color: #30363d;
    border-color: #58a6ff;
}
QPushButton:pressed {
    background-color: #1f6feb;
    color: white;
}
QPushButton:disabled {
    background-color: #161b22;
    color: #484f58;
    border-color: #21262d;
}
QPushButton#btnLong {
    background-color: #1a7f37;
    color: white;
    border: none;
    font-weight: bold;
}
QPushButton#btnLong:hover {
    background-color: #238636;
}
QPushButton#btnShort {
    background-color: #b62324;
    color: white;
    border: none;
    font-weight: bold;
}
QPushButton#btnShort:hover {
    background-color: #da3633;
}
QPushButton#btnAutoTrade {
    background-color: #1f6feb;
    color: white;
    border: none;
    font-weight: bold;
    font-size: 14px;
    padding: 10px 20px;
}
QPushButton#btnAutoTrade:hover {
    background-color: #388bfd;
}
QPushButton#btnAutoTrade:checked {
    background-color: #da3633;
}

/* ====== Combo box ====== */
QComboBox {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 20px;
}
QComboBox:hover {
    border-color: #58a6ff;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #161b22;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
    border-radius: 4px;
}

/* ====== Line edit / Spin box ====== */
QLineEdit, QDoubleSpinBox, QSpinBox {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #c9d1d9;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {
    border-color: #58a6ff;
}

/* ====== Table ====== */
QTableWidget, QTableView {
    background-color: #0d1117;
    alternate-background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 4px;
    gridline-color: #21262d;
    selection-background-color: #1f6feb;
}
QHeaderView::section {
    background-color: #161b22;
    color: #8b949e;
    border: none;
    border-bottom: 2px solid #30363d;
    padding: 6px 8px;
    font-weight: bold;
}
QTableWidget::item {
    padding: 4px 8px;
}

/* ====== Scroll bars ====== */
QScrollBar:vertical {
    background: #0d1117;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #484f58;
}
QScrollBar:horizontal {
    background: #0d1117;
    height: 10px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: #30363d;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0; width: 0;
}

/* ====== Text edit / Log area ====== */
QTextEdit, QPlainTextEdit {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 4px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
    color: #8b949e;
}

/* ====== Progress bar ====== */
QProgressBar {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    text-align: center;
    color: white;
    height: 18px;
}
QProgressBar::chunk {
    background-color: #1f6feb;
    border-radius: 5px;
}

/* ====== Status bar ====== */
QStatusBar {
    background-color: #161b22;
    border-top: 1px solid #30363d;
    color: #8b949e;
    font-size: 12px;
}

/* ====== Splitter ====== */
QSplitter::handle {
    background-color: #30363d;
}
QSplitter::handle:hover {
    background-color: #58a6ff;
}

/* ====== Labels ====== */
QLabel#lblPrice {
    font-size: 28px;
    font-weight: bold;
    color: #e6edf3;
}
QLabel#lblPositive {
    color: #3fb950;
    font-weight: bold;
}
QLabel#lblNegative {
    color: #f85149;
    font-weight: bold;
}
QLabel#lblSignalBuy {
    color: #3fb950;
    font-size: 16px;
    font-weight: bold;
}
QLabel#lblSignalSell {
    color: #f85149;
    font-size: 16px;
    font-weight: bold;
}
QLabel#lblSignalHold {
    color: #d29922;
    font-size: 16px;
    font-weight: bold;
}
QLabel#lblHeader {
    font-size: 15px;
    font-weight: bold;
    color: #58a6ff;
}

/* ====== Check box ====== */
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #30363d;
    background-color: #161b22;
}
QCheckBox::indicator:checked {
    background-color: #1f6feb;
    border-color: #1f6feb;
}

/* ====== Tool tip ====== */
QToolTip {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 4px 8px;
}
"""
