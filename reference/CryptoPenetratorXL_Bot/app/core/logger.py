"""
CryptoPenetratorXL — Comprehensive Logging System  v2.3

Three-tier logging:
  1. DEBUG file — captures *everything* (debug.log, 20 MB × 10 backups)
  2. INFO  file — operational events   (cryptopenxl.log, 10 MB × 5 backups)
  3. Console    — coloured, follows LOG_LEVEL from .env

Format includes millisecond timestamps, thread name (essential for
QThread debugging), and module path for quick navigation.

Usage:
    from app.core.logger import get_logger
    log = get_logger("gui")           # → cryptopenxl.gui
    log.debug("worker started")
    log.info("analysis done for %s", symbol)

    # Performance timing helper:
    from app.core.logger import log_perf
    with log_perf(log, "kline fetch"):
        df = client.get_klines(...)
"""

from __future__ import annotations

import logging
import sys
import time as _time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Generator

from app.core.config import LOGS_DIR, get_settings

_LOGGER_NAME = "cryptopenxl"

# Detailed format — milliseconds + thread name for QThread debugging
_FILE_FMT = (
    "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(threadName)-16s | "
    "%(name)s | %(message)s"
)
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# Console — slightly shorter (no msecs, no thread)
_CONSOLE_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_CONSOLE_DATE = "%H:%M:%S"

_initialised = False


def setup_logger() -> logging.Logger:
    """Configure and return the root application logger (idempotent).

    Creates three handlers:
      • ``debug.log``          — DEBUG level, 20 MB × 10 backups
      • ``cryptopenxl.log``    — INFO  level, 10 MB × 5 backups
      • Console (stdout)       — level from ``LOG_LEVEL`` (.env)
    """
    global _initialised
    if _initialised:
        return logging.getLogger(_LOGGER_NAME)

    settings = get_settings()
    console_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)          # capture everything; handlers filter
    logger.propagate = False

    file_formatter = logging.Formatter(_FILE_FMT, datefmt=_DATE_FMT)
    console_formatter = logging.Formatter(_CONSOLE_FMT, datefmt=_CONSOLE_DATE)

    # --- DEBUG file handler (captures everything) ---------------------------
    debug_file = LOGS_DIR / "debug.log"
    fh_debug = RotatingFileHandler(
        debug_file,
        maxBytes=20 * 1024 * 1024,  # 20 MB
        backupCount=10,
        encoding="utf-8",
    )
    fh_debug.setLevel(logging.DEBUG)
    fh_debug.setFormatter(file_formatter)
    logger.addHandler(fh_debug)

    # --- INFO file handler (operational log) --------------------------------
    info_file = LOGS_DIR / "cryptopenxl.log"
    fh_info = RotatingFileHandler(
        info_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    fh_info.setLevel(logging.INFO)
    fh_info.setFormatter(file_formatter)
    logger.addHandler(fh_info)

    # --- Console handler ----------------------------------------------------
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(console_formatter)
    logger.addHandler(ch)

    _initialised = True

    # Write session separator for easier log navigation
    sep = "=" * 80
    logger.info(sep)
    logger.info(
        "SESSION START  |  CryptoPenetratorXL  |  console=%s  |  "
        "debug=%s  |  info=%s",
        settings.log_level, debug_file, info_file,
    )
    logger.info(sep)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a child logger under the app root.

    Examples::

        get_logger()                → cryptopenxl
        get_logger("gui")          → cryptopenxl.gui
        get_logger("api.bybit")    → cryptopenxl.api.bybit
    """
    base = _LOGGER_NAME
    if name:
        return logging.getLogger(f"{base}.{name}")
    return logging.getLogger(base)


# ---------------------------------------------------------------------------
# Performance-timing context manager
# ---------------------------------------------------------------------------
@contextmanager
def log_perf(
    logger: logging.Logger,
    label: str,
    level: int = logging.DEBUG,
) -> Generator[None, None, None]:
    """Measure wall-clock time of a block and log it.

    Usage::

        with log_perf(log, "kline fetch"):
            df = client.get_klines(symbol)
        # → DEBUG  cryptopenxl.api.bybit | [PERF] kline fetch — 142.3 ms
    """
    t0 = _time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (_time.perf_counter() - t0) * 1000
        logger.log(level, "[PERF] %s — %.1f ms", label, elapsed_ms)
