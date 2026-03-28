"""
CryptoPenetratorXL — Application Entry Point

Launches the professional desktop trading terminal.
"""

import sys
import os

# Ensure the project root is on sys.path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.logger import setup_logger
from app.db.database import init_db


def main():
    # 1. Initialise logger
    logger = setup_logger()
    logger.info("=" * 60)
    logger.info("CryptoPenetratorXL v2.1.0 starting...")
    logger.info("=" * 60)

    # 2. Initialise database
    init_db()

    # 3. Launch GUI
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from app.gui.styles import DARK_THEME
    from app.gui.main_window import MainWindow

    # High-DPI — MUST be set before QApplication instantiation
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("CryptoPenetratorXL")
    app.setOrganizationName("CryptoPenXL")
    app.setStyleSheet(DARK_THEME)

    window = MainWindow()
    window.show()

    logger.info("GUI launched successfully")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
