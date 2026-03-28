"""
CryptoPenetratorXL — Main Application Window

Professional trading terminal with:
  - Live candlestick chart + 4 indicator sub-plots
  - Signal dashboard with confluence scoring
  - One-click manual & auto trading
  - Positions panel with real-time P&L
  - Trade history & statistics
  - Activity log
  - Settings dialog
"""

from __future__ import annotations

import time as _time
import traceback
import winsound
from datetime import datetime, timezone
from functools import partial
from typing import Any

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal, pyqtSlot, QSize, QStringListModel, QSortFilterProxyModel
from PyQt6.QtGui import QAction, QIcon, QFont, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from app.analysis.enhanced_analysis import EnhancedAnalysisEngine, EnhancedAnalysisResult
from app.api.bybit_client import BybitClient
from app.core.config import get_settings
from app.core.constants import Signal, Side, Timeframe
from app.core.logger import get_logger
from app.db import database as db
from app.gui.analytics_widget import AnalyticsWidget
from app.gui.chart_widget import ChartWidget
from app.gui.styles import DARK_THEME
from app.indicators.engine import IndicatorEngine
from app.strategy.signal_generator import SignalGenerator, TradeSignal
from app.trading.executor import TradeExecutor
from app.trading.paper_manager import PaperPositionManager
from app.utils.helpers import fmt_price, fmt_pct, fmt_qty, utcnow

log = get_logger("gui")

# ======================================================================
# .env persistence helpers
# ======================================================================
from pathlib import Path as _Path
import json as _json

_ENV_PATH = _Path(__file__).resolve().parent.parent.parent / ".env"
_SESSION_PATH = _Path(__file__).resolve().parent.parent.parent / "data" / "session_state.json"


def _update_env_file(new_vals: dict[str, str]) -> None:
    """Merge *new_vals* into the .env file, preserving comments and order."""
    lines: list[str] = []
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)

    updated_keys: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip blank / comment lines — keep them as-is
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        # Parse KEY=VALUE
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in new_vals:
                out.append(f"{key}={new_vals[key]}\n")
                updated_keys.add(key)
                continue
        out.append(line)

    # Append any new keys that weren't already in the file
    for key, val in new_vals.items():
        if key not in updated_keys:
            out.append(f"{key}={val}\n")

    _ENV_PATH.write_text("".join(out), encoding="utf-8")
    log.info("_update_env_file  wrote %d key(s) to %s", len(new_vals), _ENV_PATH)


def _save_session_state(data: dict) -> None:
    """Persist UI session state (symbol, timeframe, etc.) to JSON."""
    _SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SESSION_PATH.write_text(_json.dumps(data, indent=2), encoding="utf-8")


def _load_session_state() -> dict:
    """Load UI session state from JSON, or return empty dict."""
    if _SESSION_PATH.exists():
        try:
            return _json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ======================================================================
# Worker threads
# ======================================================================
class AnalysisWorker(QThread):
    """Run analysis in a background thread to keep UI responsive."""
    result_ready = pyqtSignal(object, object)  # (TradeSignal | None, enriched_df | None)
    error = pyqtSignal(str)

    def __init__(self, generator: SignalGenerator, symbol: str, timeframe: str):
        super().__init__()
        self.generator = generator
        self.symbol = symbol
        self.timeframe = timeframe

    def run(self):
        log.debug("[AnalysisWorker] started  symbol=%s  tf=%s", self.symbol, self.timeframe)
        try:
            df = self.generator.client.get_klines(self.symbol, self.timeframe, 200)
            log.debug("[AnalysisWorker] klines fetched  rows=%d", len(df))
            df = self.generator.engine.enrich(df)
            signal = self.generator.generate_from_df(df, self.symbol, self.timeframe)
            log.debug("[AnalysisWorker] done  signal=%s  conf=%.2f", signal.signal.value, signal.confidence)
            self.result_ready.emit(signal, df)
        except Exception as e:
            log.error("[AnalysisWorker] FAILED: %s", e, exc_info=True)
            self.error.emit(str(e))


class AutoTradeWorker(QThread):
    """Smart auto-trading loop: analyse → open → monitor TP → close → repeat."""
    signal_generated = pyqtSignal(object)   # TradeSignal
    chart_data_ready = pyqtSignal(object, object)  # (TradeSignal, DataFrame) for chart update
    trade_executed = pyqtSignal(object)     # dict result (open)
    trade_closed = pyqtSignal(object)       # dict result (TP hit / close)
    position_update = pyqtSignal(object)    # dict — mark-price refresh
    log_message = pyqtSignal(str)
    countdown = pyqtSignal(int)             # seconds remaining
    error = pyqtSignal(str)

    # Timing constants
    _MONITOR_INTERVAL = 5   # seconds between TP checks when position is open
    # Limit order offset — small % above/below market to ensure near-instant fill
    _LIMIT_OFFSET_PCT = 0.0001  # 0.01%

    def __init__(self, generator: SignalGenerator, executor: TradeExecutor,
                 paper_manager: PaperPositionManager,
                 symbol: str, timeframe: str, interval_sec: int):
        super().__init__()
        self.generator = generator
        self.executor = executor
        self.paper_mgr = paper_manager
        self.symbol = symbol
        self.timeframe = timeframe
        self.interval_sec = interval_sec
        self._running = True

    def run(self):
        import time
        log.info("[AutoTradeWorker] STARTED  symbol=%s  tf=%s  interval=%ds",
                 self.symbol, self.timeframe, self.interval_sec)
        while self._running:
            try:
                has_pos = self._has_any_position()
                if has_pos:
                    self._monitor_position()
                    wait = self._MONITOR_INTERVAL
                else:
                    self._analyse_and_trade()
                    wait = self.interval_sec
            except Exception as e:
                log.error("[AutoTradeWorker] loop error: %s", e, exc_info=True)
                self.error.emit(f"{self.symbol}: {e}")
                wait = self.interval_sec

            # Countdown sleep
            if self._running:
                for remaining in range(wait, 0, -1):
                    if not self._running:
                        break
                    self.countdown.emit(remaining)
                    time.sleep(1)
                self.countdown.emit(0)

    def _has_any_position(self) -> bool:
        """Check for open positions in both paper manager and live exchange."""
        # Paper positions
        if self.paper_mgr.has_position(self.symbol):
            return True
        # Live positions — query the exchange
        try:
            positions = self.generator.client.get_positions(self.symbol)
            return len(positions) > 0
        except Exception as e:
            log.debug("[AutoTradeWorker] _has_any_position live check: %s", e)
            return False

    # ---- phases ----------------------------------------------------------
    def _monitor_position(self):
        """Refresh mark price for the open position and check TP.

        Handles both paper positions (via paper_mgr) and live positions
        (via exchange API).
        """
        try:
            ticker = self.generator.client.get_ticker(self.symbol)
            mark = float(ticker.get("lastPrice", 0))
            if mark <= 0:
                return

            # --- Paper position monitoring ---
            if self.paper_mgr.has_position(self.symbol):
                self.paper_mgr.update_mark_price(self.symbol, mark)
                pos = self.paper_mgr.get_position(self.symbol)
                if pos:
                    self.position_update.emit(pos)
                # Check TP hit
                if self.paper_mgr.check_tp(self.symbol, mark):
                    closed = self.paper_mgr.close(self.symbol, mark)
                    if closed:
                        self.trade_closed.emit(closed)
                        db.close_trade(
                            closed["order_id"], mark,
                            closed["pnl"], closed["pnl_pct"],
                        )
                        self.log_message.emit(
                            f"TP HIT \u2714  {closed['side']} {self.symbol}  "
                            f"exit={fmt_price(mark)}  PnL=${closed['pnl']:+.2f} ({closed['pnl_pct']:+.2f}%)"
                        )
                return

            # --- Live position monitoring ---
            try:
                positions = self.generator.client.get_positions(self.symbol)
            except Exception as e:
                log.debug("[AutoTradeWorker] live position fetch: %s", e)
                return

            if not positions:
                # Position was closed externally (e.g. TP hit on exchange)
                self.log_message.emit(
                    f"Position closed externally for {self.symbol}"
                )
                return

            pos = positions[0]
            self.position_update.emit(pos)

        except Exception as e:
            log.debug("[AutoTradeWorker] monitor error: %s", e)

    def _analyse_and_trade(self):
        """Analyse market → open position if signal is actionable."""
        self.log_message.emit(f"Analysing {self.symbol}...")

        # Fetch klines and enrich so we can send the DataFrame for chart update
        try:
            df = self.generator.client.get_klines(
                self.symbol, interval=self.timeframe, limit=200,
            )
            df = self.generator.engine.enrich(df)
            signal = self.generator.generate_from_df(df, self.symbol, self.timeframe)
        except Exception as e:
            log.error("[AutoTradeWorker] analyse failed: %s", e)
            self.error.emit(f"{self.symbol}: {e}")
            return

        self.signal_generated.emit(signal)
        self.chart_data_ready.emit(signal, df)

        if signal.signal in (Signal.STRONG_BUY, Signal.STRONG_SELL,
                             Signal.BUY, Signal.SELL):
            self.log_message.emit(
                f"Trade signal: {signal.signal.value} {self.symbol} "
                f"conf={signal.confidence:.2f} TP={signal.tp_pct:.2f}%"
            )
            try:
                result = self.executor.execute(signal)
            except Exception as e:
                log.error("[AutoTradeWorker] execute failed: %s", e, exc_info=True)
                self.error.emit(f"{self.symbol}: order failed — {e}")
                db.save_signal(signal.to_dict())
                return
            self.trade_executed.emit(result)
            if result.get("status") in ("filled", "paper_filled"):
                if result.get("mode") == "paper":
                    self.paper_mgr.open(result)
                db.save_trade(result)
            db.save_signal(signal.to_dict())
        else:
            db.save_signal(signal.to_dict())

    def stop(self):
        log.info("[AutoTradeWorker] stop requested")
        self._running = False


class SymbolFetchWorker(QThread):
    """Background thread to fetch all available USDT linear symbols from Bybit."""
    symbols_ready = pyqtSignal(list)  # list[str]

    def __init__(self, client: BybitClient):
        super().__init__()
        self.client = client

    def run(self):
        log.debug("[SymbolFetchWorker] started")
        try:
            tickers = self.client.get_tickers()
            symbols = sorted(
                t["symbol"] for t in tickers
                if t.get("symbol", "").endswith("USDT")
            )
            log.info("[SymbolFetchWorker] fetched %d USDT pairs", len(symbols))
            self.symbols_ready.emit(symbols)
        except Exception as e:
            log.error("[SymbolFetchWorker] FAILED: %s", e, exc_info=True)
            self.symbols_ready.emit([])


class MTFWorker(QThread):
    """Analyse multiple timeframes in a background thread for MTF confluence."""
    result_ready = pyqtSignal(dict)  # {tf_value: {"signal": str, "confidence": float, "confluence": float}}

    def __init__(self, generator: SignalGenerator, symbol: str, timeframes: list[str]):
        super().__init__()
        self.generator = generator
        self.symbol = symbol
        self.timeframes = timeframes

    def run(self):
        log.debug("[MTFWorker] started  symbol=%s  tfs=%s", self.symbol, self.timeframes)
        results: dict[str, dict] = {}
        for tf in self.timeframes:
            try:
                signal = self.generator.generate(self.symbol, tf)
                results[tf] = {
                    "signal": signal.signal.value,
                    "confidence": round(signal.confidence, 2),
                    "confluence": round(signal.indicator_detail.get("confluence_score", 0), 4),
                }
                log.debug("[MTFWorker] %s/%s → %s  conf=%.2f",
                          self.symbol, tf, signal.signal.value, signal.confidence)
            except Exception as e:
                log.warning("[MTFWorker] %s/%s FAILED: %s", self.symbol, tf, e)
                results[tf] = {"signal": "ERR", "confidence": 0, "confluence": 0}
        log.debug("[MTFWorker] done  %d timeframes", len(results))
        self.result_ready.emit(results)


class EnhancedAnalysisWorker(QThread):
    """Run enhanced (deep) analysis in background thread."""
    result_ready = pyqtSignal(object)  # EnhancedAnalysisResult
    error = pyqtSignal(str)

    def __init__(self, engine: EnhancedAnalysisEngine, df):
        super().__init__()
        self.engine = engine
        self.df = df

    def run(self):
        log.debug("[EnhancedWorker] started  rows=%d", len(self.df))
        try:
            result = self.engine.analyse(self.df)
            log.debug(
                "[EnhancedWorker] done  patterns=%d  structures=%d  prob_up=%.0f%%",
                len(result.candle_patterns), len(result.structures),
                result.forecast.prob_up * 100,
            )
            self.result_ready.emit(result)
        except Exception as e:
            log.error("[EnhancedWorker] FAILED: %s", e, exc_info=True)
            self.error.emit(str(e))


class PositionsWorker(QThread):
    """Fetch wallet balance + open positions in a background thread.

    In paper mode the worker:
      1. Uses a fixed simulated wallet.
      2. Pulls all paper positions from *PaperPositionManager*.
      3. For each paper position it fetches the latest ticker from Bybit
         (mainnet) and updates the mark price / unrealised P&L.
      4. Checks if any position has hit its TP and auto-closes it.
    """

    result_ready = pyqtSignal(dict, list)  # (wallet_dict, positions_list)
    trade_closed = pyqtSignal(object)      # closed paper position dict  (TP hit)
    error = pyqtSignal(str)

    _PAPER_WALLET: dict = {
        "equity": 10_000.0,
        "available": 10_000.0,
        "wallet_balance": 10_000.0,
        "unrealised_pnl": 0.0,
    }

    def __init__(self, client: BybitClient,
                 paper_mode: bool = False,
                 paper_manager: PaperPositionManager | None = None):
        super().__init__()
        self.client = client
        self._paper = paper_mode
        self._pm = paper_manager

    def run(self):
        log.debug("[PositionsWorker] started  paper=%s", self._paper)
        try:
            if self._paper:
                wallet = dict(self._PAPER_WALLET)
                # Update mark prices for every paper position
                if self._pm is not None:
                    for pos in self._pm.get_positions():
                        try:
                            ticker = self.client.get_ticker(pos["symbol"])
                            mark = float(ticker.get("lastPrice", 0))
                            if mark > 0:
                                self._pm.update_mark_price(pos["symbol"], mark)
                        except Exception:
                            pass
                        # Auto-close on TP hit
                        if self._pm.check_tp(pos["symbol"], pos.get("mark_price", 0)):
                            closed = self._pm.close(pos["symbol"], pos["mark_price"])
                            if closed:
                                db.close_trade(
                                    closed["order_id"], closed["mark_price"],
                                    closed["pnl"], closed["pnl_pct"],
                                )
                                self.trade_closed.emit(closed)
                    positions = self._pm.get_positions()
                    # Reflect unrealised PnL in wallet
                    total_upnl = sum(p.get("unrealised_pnl", 0) for p in positions)
                    wallet["unrealised_pnl"] = round(total_upnl, 4)
                else:
                    positions = []
            else:
                wallet = self.client.get_wallet_balance()
                positions = self.client.get_positions()
            log.debug(
                "[PositionsWorker] done  equity=$%.2f  positions=%d",
                wallet.get('equity', 0), len(positions),
            )
            self.result_ready.emit(wallet, positions)
        except Exception as e:
            log.warning("[PositionsWorker] FAILED: %s", e)
            self.error.emit(str(e))


class LatencyWorker(QThread):
    """Ping Bybit server time in a background thread."""
    result_ready = pyqtSignal(float)  # latency in ms
    error = pyqtSignal(str)

    def __init__(self, client: BybitClient):
        super().__init__()
        self.client = client

    def run(self):
        try:
            t0 = _time.monotonic()
            self.client.session.get_server_time()
            ms = (_time.monotonic() - t0) * 1000
            log.debug("[LatencyWorker] ping=%.0fms", ms)
            self.result_ready.emit(ms)
        except Exception as e:
            log.debug("[LatencyWorker] FAILED: %s", e)
            self.error.emit(str(e))


class SmartSymbolCombo(QComboBox):
    """
    Editable QComboBox with instant substring-match autocomplete.
    Dropdown shows only symbols matching the typed text.

    Emits ``symbol_selected(str)`` ONLY when the user explicitly
    chooses a symbol:
      • clicks an item in the dropdown / completer popup
      • presses Enter after typing

    Typing alone does NOT trigger the signal — this prevents
    every keystroke from launching an analysis run.
    """

    symbol_selected = pyqtSignal(str)   # emitted on confirmed selection only

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumWidth(170)
        self.setMaxVisibleItems(12)

        # Build a completer with substring matching
        self._completer = QCompleter(self)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setMaxVisibleItems(15)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(self._completer)

        # Start with default set, then update once Bybit responds
        self._all_symbols: list[str] = []

        # --- Connect the "confirmed selection" signals ---
        # 1) User clicks an item in the dropdown popup
        self.activated.connect(self._on_activated)
        # 2) User picks an item from the completer popup
        self._completer.activated.connect(self._on_completer_activated)
        # 3) User presses Enter in the line-edit
        self.lineEdit().returnPressed.connect(self._on_return_pressed)

    # -- internal slots ---
    def _on_activated(self, _index: int):
        text = self.currentText().strip().upper()
        if text:
            log.debug("SmartSymbolCombo: activated index=%d → %s", _index, text)
            self.symbol_selected.emit(text)

    def _on_completer_activated(self, text: str):
        text = text.strip().upper()
        if text:
            log.debug("SmartSymbolCombo: completer activated → %s", text)
            # Set combo to this text (completer selection doesn't always update it)
            idx = self.findText(text, Qt.MatchFlag.MatchExactly)
            if idx >= 0:
                self.setCurrentIndex(idx)
            else:
                self.setCurrentText(text)
            self.symbol_selected.emit(text)

    def _on_return_pressed(self):
        text = self.lineEdit().text().strip().upper()
        if not text:
            return
        log.debug("SmartSymbolCombo: Enter pressed → %s", text)
        # Validate against known symbols
        idx = self.findText(text, Qt.MatchFlag.MatchExactly)
        if idx >= 0:
            self.setCurrentIndex(idx)
            self.symbol_selected.emit(text)
        else:
            # User typed something not in list — ignore or pick closest
            log.info("SmartSymbolCombo: '%s' not in symbol list — ignored", text)

    def set_symbols(self, symbols: list[str]):
        """Replace the full symbol list (called once Bybit data arrives)."""
        self._all_symbols = symbols
        current = self.currentText()
        # Block signals to prevent cascading during rebuild
        self.blockSignals(True)
        self.clear()
        self.addItems(symbols)
        idx = self.findText(current, Qt.MatchFlag.MatchExactly)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            self.setCurrentText(current)
        self.blockSignals(False)
        # Update completer model
        model = QStringListModel(symbols, self)
        self._completer.setModel(model)


# ======================================================================
# Settings dialog
# ======================================================================
class SettingsDialog(QDialog):
    """Modal settings dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(420, 500)
        self._cfg = get_settings()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # -- API keys
        grp_api = QGroupBox("Bybit API")
        form_api = QFormLayout()
        self.edit_api_key = QLineEdit(self._cfg.bybit_api_key)
        self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_secret = QLineEdit(self._cfg.bybit_secret_key)
        self.edit_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.chk_testnet = QCheckBox()
        self.chk_testnet.setChecked(self._cfg.bybit_testnet)
        form_api.addRow("API Key:", self.edit_api_key)
        form_api.addRow("Secret:", self.edit_secret)
        form_api.addRow("Testnet:", self.chk_testnet)
        grp_api.setLayout(form_api)
        layout.addWidget(grp_api)

        # -- Trading
        grp_trade = QGroupBox("Trading")
        form_trade = QFormLayout()
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["paper", "live"])
        self.cmb_mode.setCurrentText(self._cfg.trading_mode)
        self.spin_leverage = QDoubleSpinBox()
        self.spin_leverage.setRange(1.0, 10.0)
        self.spin_leverage.setSingleStep(0.5)
        self.spin_leverage.setValue(self._cfg.default_leverage)
        self.spin_max_lev = QDoubleSpinBox()
        self.spin_max_lev.setRange(1.0, 10.0)
        self.spin_max_lev.setSingleStep(0.5)
        self.spin_max_lev.setValue(self._cfg.max_leverage)
        form_trade.addRow("Mode:", self.cmb_mode)
        form_trade.addRow("Default Leverage:", self.spin_leverage)
        form_trade.addRow("Max Leverage:", self.spin_max_lev)
        grp_trade.setLayout(form_trade)
        layout.addWidget(grp_trade)

        # -- Strategy
        grp_strat = QGroupBox("Strategy")
        form_strat = QFormLayout()
        self.chk_full_balance = QCheckBox("Use 100% of equity")
        self.chk_full_balance.setChecked(self._cfg.use_full_balance)
        self.chk_use_sl = QCheckBox("Enable Stop Loss")
        self.chk_use_sl.setChecked(self._cfg.use_stop_loss)
        self.spin_tp = QDoubleSpinBox()
        self.spin_tp.setRange(0.1, 10.0)
        self.spin_tp.setDecimals(2)
        self.spin_tp.setSuffix("%")
        self.spin_tp.setValue(self._cfg.take_profit_pct * 100)
        self.spin_fee = QDoubleSpinBox()
        self.spin_fee.setRange(0.0, 1.0)
        self.spin_fee.setDecimals(4)
        self.spin_fee.setSuffix("%")
        self.spin_fee.setValue(self._cfg.exchange_fee_pct * 100)
        form_strat.addRow("Full Balance:", self.chk_full_balance)
        form_strat.addRow("Stop Loss:", self.chk_use_sl)
        form_strat.addRow("Take Profit:", self.spin_tp)
        form_strat.addRow("Exchange Fee:", self.spin_fee)
        grp_strat.setLayout(form_strat)
        layout.addWidget(grp_strat)

        # -- Auto-trade / UI
        grp_ui = QGroupBox("Auto-Trade && Display")
        form_ui = QFormLayout()
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(5, 300)
        self.spin_interval.setSingleStep(5)
        self.spin_interval.setSuffix(" s")
        self.spin_interval.setValue(self._cfg.monitor_interval_sec)
        self.spin_interval.setToolTip("Interval between analysis cycles (seconds)")
        self.chk_trade_overlay = QCheckBox("Show entry / TP lines on chart")
        # Load overlay preference from session state
        _ses = _load_session_state()
        self.chk_trade_overlay.setChecked(_ses.get("show_trade_overlay", True))
        self.chk_crosshair = QCheckBox("Enable crosshair on chart")
        self.chk_crosshair.setChecked(_ses.get("crosshair_enabled", True))
        self.chk_crosshair.setToolTip("Show interactive crosshair with indicator values when hovering over the chart")
        form_ui.addRow("Analysis Interval:", self.spin_interval)
        form_ui.addRow("Trade Overlay:", self.chk_trade_overlay)
        form_ui.addRow("Crosshair:", self.chk_crosshair)
        grp_ui.setLayout(form_ui)
        layout.addWidget(grp_ui)

        # -- Buttons
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_values(self) -> dict[str, Any]:
        """Return all dialog field values as a dict keyed by .env variable name."""
        return {
            "BYBIT_API_KEY": self.edit_api_key.text().strip(),
            "BYBIT_SECRET_KEY": self.edit_secret.text().strip(),
            "BYBIT_TESTNET": str(self.chk_testnet.isChecked()).lower(),
            "TRADING_MODE": self.cmb_mode.currentText(),
            "DEFAULT_LEVERAGE": str(self.spin_leverage.value()),
            "MAX_LEVERAGE": str(self.spin_max_lev.value()),
            "USE_FULL_BALANCE": str(self.chk_full_balance.isChecked()).lower(),
            "USE_STOP_LOSS": str(self.chk_use_sl.isChecked()).lower(),
            "TAKE_PROFIT_PCT": str(self.spin_tp.value() / 100),
            "EXCHANGE_FEE_PCT": str(self.spin_fee.value() / 100),
            "MONITOR_INTERVAL_SEC": str(self.spin_interval.value()),
        }

    def get_overlay_pref(self) -> bool:
        """Return the user's trade-overlay toggle preference."""
        return self.chk_trade_overlay.isChecked()

    def get_crosshair_pref(self) -> bool:
        """Return the user's crosshair toggle preference."""
        return self.chk_crosshair.isChecked()


# ======================================================================
# Main Window
# ======================================================================
class MainWindow(QMainWindow):
    """CryptoPenetratorXL main application window."""

    def __init__(self):
        super().__init__()
        log.info("MainWindow.__init__ started")
        self.setWindowTitle("CryptoPenetratorXL  —  Professional Crypto Trading Terminal")
        self.setMinimumSize(1400, 900)
        self.resize(1600, 1000)

        self._cfg = get_settings()

        # -- Core services
        self.client = BybitClient()
        self.engine = IndicatorEngine()
        self.generator = SignalGenerator(self.client)
        self.executor = TradeExecutor(self.client)
        self.paper_manager = PaperPositionManager()
        self.executor.risk.paper_manager = self.paper_manager

        # -- State  (restore from session file, fallback to .env defaults)
        _session = _load_session_state()
        self._current_symbol = _session.get(
            "symbol",
            self._cfg.default_symbols[0] if self._cfg.default_symbols else "BTCUSDT",
        )
        self._current_tf = _session.get("timeframe", self._cfg.default_timeframe)
        self._auto_worker: AutoTradeWorker | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._mtf_worker: MTFWorker | None = None
        self._enhanced_worker: EnhancedAnalysisWorker | None = None
        self._last_signal: TradeSignal | None = None
        self._current_df = None
        self._signal_history: list[dict] = []   # for chart markers
        self._sound_enabled = True
        self._enhanced_mode = False
        self._enhanced_engine = EnhancedAnalysisEngine()
        self._cached_equity: float = 0.0  # cached from _refresh_positions
        self._positions_worker: PositionsWorker | None = None
        self._latency_worker: LatencyWorker | None = None
        self._show_trade_overlay: bool = _session.get("show_trade_overlay", True)
        self._crosshair_enabled: bool = _session.get("crosshair_enabled", True)

        # -- Build UI
        self._build_menu()
        self._build_central()
        self._build_status_bar()
        self._build_hotkeys()

        # -- Timers
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh_timer)
        self._refresh_timer.start(60_000)  # auto-refresh every 60s

        self._positions_timer = QTimer(self)
        self._positions_timer.timeout.connect(self._refresh_positions)
        self._positions_timer.start(15_000)  # positions every 15s

        # Latency ping timer (every 30s)
        self._latency_timer = QTimer(self)
        self._latency_timer.timeout.connect(self._update_latency)
        self._latency_timer.start(30_000)

        # Fast price ticker — update displayed price every 5 seconds
        self._price_ticker_timer = QTimer(self)
        self._price_ticker_timer.timeout.connect(self._fast_price_update)
        self._price_ticker_timer.start(5_000)

        # Debounce timer — prevent rapid overlapping analysis calls
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)  # 300ms
        self._debounce_timer.timeout.connect(self._do_analysis)

        # -- Apply crosshair preference after chart is built
        self.chart.toggle_crosshair(self._crosshair_enabled)

        # -- Initial load
        QTimer.singleShot(500, self._initial_load)
        log.info("MainWindow.__init__ complete  [symbol=%s, tf=%s, mode=%s]",
                 self._current_symbol, self._current_tf, self._cfg.trading_mode)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def _build_menu(self):
        menu = self.menuBar()

        # File
        file_menu = menu.addMenu("&File")
        act_settings = QAction("Settings", self)
        act_settings.triggered.connect(self._open_settings)
        file_menu.addAction(act_settings)
        file_menu.addSeparator()
        act_quit = QAction("Exit", self)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # Trading
        trade_menu = menu.addMenu("&Trading")
        act_analyse = QAction("Analyse Now", self)
        act_analyse.triggered.connect(self._run_analysis)
        trade_menu.addAction(act_analyse)
        act_close_all = QAction("Close All Positions", self)
        act_close_all.triggered.connect(self._close_all_positions)
        trade_menu.addAction(act_close_all)

        # View
        view_menu = menu.addMenu("&View")
        act_refresh = QAction("Refresh", self)
        act_refresh.triggered.connect(self._run_analysis)
        view_menu.addAction(act_refresh)

    # ------------------------------------------------------------------
    # Central widget
    # ------------------------------------------------------------------
    def _build_central(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # -- Top bar: symbol selector + timeframe + action buttons
        top_bar = self._build_top_bar()
        main_layout.addLayout(top_bar)

        # -- Main splitter: chart (left) + panels (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: chart
        self.chart = ChartWidget(self)
        splitter.addWidget(self.chart)

        # Right: tabs (Signal, Positions, History, Log)
        right_panel = self._build_right_panel()
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        main_layout.addWidget(splitter, stretch=1)

    def _build_top_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        # Symbol
        lbl_sym = QLabel("Symbol:")
        lbl_sym.setObjectName("lblHeader")
        self.cmb_symbol = SmartSymbolCombo()
        # Seed with defaults; Bybit full list loaded async
        seed = self._cfg.default_symbols + [
            "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "ADAUSDT", "DOTUSDT",
            "MATICUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
        ]
        seed = list(dict.fromkeys(seed))
        self.cmb_symbol.addItems(seed)
        self.cmb_symbol.setCurrentText(self._current_symbol)
        self.cmb_symbol.symbol_selected.connect(self._on_symbol_changed)

        # Timeframe
        lbl_tf = QLabel("Timeframe:")
        self.cmb_tf = QComboBox()
        for tf in Timeframe:
            self.cmb_tf.addItem(tf.label, tf.value)
        idx = self.cmb_tf.findData(self._current_tf)
        if idx >= 0:
            self.cmb_tf.setCurrentIndex(idx)
        self.cmb_tf.currentIndexChanged.connect(self._on_tf_changed)

        # Analyse button
        self.btn_analyse = QPushButton("  Analyse")
        self.btn_analyse.setMinimumWidth(110)
        self.btn_analyse.clicked.connect(self._run_analysis)

        # Price label
        self.lbl_price = QLabel("—")
        self.lbl_price.setObjectName("lblPrice")
        self.lbl_change = QLabel("")

        # Ideal Scenario toggle
        self.btn_ideal = QPushButton("Ideal Scenario")
        self.btn_ideal.setCheckable(True)
        self.btn_ideal.setToolTip("Show ideal entry conditions on the chart  [F6]")
        self.btn_ideal.toggled.connect(self._toggle_ideal_scenario)

        # Enhanced Analysis toggle
        self.btn_enhanced = QPushButton("🧠 Enhanced")
        self.btn_enhanced.setCheckable(True)
        self.btn_enhanced.setToolTip("Deep analysis: patterns, structures, probability  [F8]")
        self.btn_enhanced.toggled.connect(self._toggle_enhanced_mode)

        # Sound toggle
        self.btn_sound = QPushButton("🔔")
        self.btn_sound.setCheckable(True)
        self.btn_sound.setChecked(True)
        self.btn_sound.setToolTip("Sound alerts on BUY/SELL signals  [F7]")
        self.btn_sound.setMaximumWidth(36)
        self.btn_sound.toggled.connect(lambda on: setattr(self, '_sound_enabled', on))

        # Auto-trade toggle
        self.btn_auto = QPushButton("  AUTO TRADE")
        self.btn_auto.setObjectName("btnAutoTrade")
        self.btn_auto.setCheckable(True)
        self.btn_auto.setMinimumWidth(140)
        self.btn_auto.toggled.connect(self._toggle_auto_trade)

        # Mode indicator
        mode = self._cfg.trading_mode.upper()
        self.lbl_mode = QLabel(f"[{mode}]")
        self.lbl_mode.setStyleSheet(
            "color: #3fb950; font-weight: bold;" if mode == "PAPER"
            else "color: #f85149; font-weight: bold; font-size: 14px;"
        )

        layout.addWidget(lbl_sym)
        layout.addWidget(self.cmb_symbol)
        layout.addSpacing(12)
        layout.addWidget(lbl_tf)
        layout.addWidget(self.cmb_tf)
        layout.addSpacing(12)
        layout.addWidget(self.btn_analyse)
        layout.addSpacing(8)
        layout.addWidget(self.btn_ideal)
        layout.addWidget(self.btn_enhanced)
        layout.addWidget(self.btn_sound)
        layout.addSpacing(20)
        layout.addWidget(self.lbl_price)
        layout.addWidget(self.lbl_change)
        layout.addStretch()
        layout.addWidget(self.lbl_mode)
        layout.addSpacing(8)
        layout.addWidget(self.btn_auto)

        return layout

    def _build_right_panel(self) -> QTabWidget:
        tabs = QTabWidget()

        # Tab 1: Signal Dashboard
        self.signal_tab = self._build_signal_tab()
        tabs.addTab(self.signal_tab, "Signal")

        # Tab 2: Positions
        self.positions_tab = self._build_positions_tab()
        tabs.addTab(self.positions_tab, "Positions")

        # Tab 3: History
        self.history_tab = self._build_history_tab()
        tabs.addTab(self.history_tab, "History")

        # Tab 4: Log
        self.log_tab = self._build_log_tab()
        tabs.addTab(self.log_tab, "Log")

        # Tab 5: Analytics
        self.analytics_widget = AnalyticsWidget(self)
        tabs.addTab(self.analytics_widget, "Analytics")

        return tabs

    # -- Signal tab --------------------------------------------------------
    def _build_signal_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Signal summary
        self.lbl_signal = QLabel("HOLD")
        self.lbl_signal.setObjectName("lblSignalHold")
        self.lbl_signal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_signal)

        # Confidence bar
        self.bar_confidence = QProgressBar()
        self.bar_confidence.setRange(0, 100)
        self.bar_confidence.setValue(0)
        self.bar_confidence.setFormat("Confidence: %p%")
        layout.addWidget(self.bar_confidence)

        # Indicator details
        grp = QGroupBox("Indicator Breakdown")
        grid = QFormLayout()

        self.lbl_vol_score = QLabel("—")
        self.lbl_stoch_score = QLabel("—")
        self.lbl_macd_score = QLabel("—")
        self.lbl_cci_score = QLabel("—")
        self.lbl_confluence = QLabel("—")
        self.lbl_candle = QLabel("—")

        grid.addRow("Volume:", self.lbl_vol_score)
        grid.addRow("Stochastic:", self.lbl_stoch_score)
        grid.addRow("MACD:", self.lbl_macd_score)
        grid.addRow("CCI:", self.lbl_cci_score)
        grid.addRow("Confluence:", self.lbl_confluence)
        grid.addRow("Candle:", self.lbl_candle)
        grp.setLayout(grid)
        layout.addWidget(grp)

        # Multi-Timeframe Confluence
        grp_mtf = QGroupBox("Multi-Timeframe Confluence")
        mtf_grid = QFormLayout()
        self.lbl_mtf_5m = QLabel("—")
        self.lbl_mtf_15m = QLabel("—")
        self.lbl_mtf_1h = QLabel("—")
        self.lbl_mtf_4h = QLabel("—")
        mtf_grid.addRow("5 min:", self.lbl_mtf_5m)
        mtf_grid.addRow("15 min:", self.lbl_mtf_15m)
        mtf_grid.addRow("1 hour:", self.lbl_mtf_1h)
        mtf_grid.addRow("4 hour:", self.lbl_mtf_4h)
        grp_mtf.setLayout(mtf_grid)
        layout.addWidget(grp_mtf)

        # Trade details
        grp2 = QGroupBox("Trade Setup")
        grid2 = QFormLayout()
        self.lbl_entry = QLabel("—")
        self.lbl_sl = QLabel("No SL")
        self.lbl_tp = QLabel("—")
        self.lbl_tp_net = QLabel("—")
        self.lbl_leverage = QLabel("—")
        self.lbl_equity = QLabel("—")
        grid2.addRow("Entry:", self.lbl_entry)
        grid2.addRow("Stop Loss:", self.lbl_sl)
        grid2.addRow("Take Profit:", self.lbl_tp)
        grid2.addRow("Net TP (fees):", self.lbl_tp_net)
        grid2.addRow("Leverage:", self.lbl_leverage)
        grid2.addRow("Position:", self.lbl_equity)
        grp2.setLayout(grid2)
        layout.addWidget(grp2)

        # Risk Calculator
        grp_risk = QGroupBox("Risk Calculator")
        risk_grid = QFormLayout()
        self.lbl_risk_position = QLabel("—")
        self.lbl_risk_profit = QLabel("—")
        self.lbl_risk_liq_dist = QLabel("—")
        self.lbl_risk_rr = QLabel("—")
        risk_grid.addRow("Position $:", self.lbl_risk_position)
        risk_grid.addRow("Profit @ TP:", self.lbl_risk_profit)
        risk_grid.addRow("Liq. distance:", self.lbl_risk_liq_dist)
        risk_grid.addRow("Risk/Reward:", self.lbl_risk_rr)
        grp_risk.setLayout(risk_grid)
        layout.addWidget(grp_risk)

        # Last Trade summary
        grp_last = QGroupBox("Last Trade")
        last_grid = QFormLayout()
        self.lbl_last_trade = QLabel("No trades yet")
        self.lbl_last_trade.setWordWrap(True)
        self.lbl_last_trade.setStyleSheet("color: #8b949e;")
        last_grid.addRow(self.lbl_last_trade)
        grp_last.setLayout(last_grid)
        layout.addWidget(grp_last)

        # Enhanced Analysis (visible only when mode is ON)
        self.grp_enhanced = QGroupBox("🧠 Enhanced Analysis")
        self.grp_enhanced.setVisible(False)
        enh_grid = QFormLayout()
        self.lbl_enh_patterns = QLabel("—")
        self.lbl_enh_patterns.setWordWrap(True)
        self.lbl_enh_structures = QLabel("—")
        self.lbl_enh_structures.setWordWrap(True)
        self.lbl_enh_probability = QLabel("—")
        self.lbl_enh_probability.setWordWrap(True)
        self.lbl_enh_psych = QLabel("—")
        self.lbl_enh_psych.setWordWrap(True)
        self.lbl_enh_forecast = QLabel("—")
        self.lbl_enh_forecast.setWordWrap(True)
        enh_grid.addRow("Candle Patterns:", self.lbl_enh_patterns)
        enh_grid.addRow("Chart Structure:", self.lbl_enh_structures)
        enh_grid.addRow("Probability:", self.lbl_enh_probability)
        enh_grid.addRow("Psychology:", self.lbl_enh_psych)
        enh_grid.addRow("Forecast:", self.lbl_enh_forecast)
        self.grp_enhanced.setLayout(enh_grid)
        layout.addWidget(self.grp_enhanced)

        # Manual trade buttons
        btn_layout = QHBoxLayout()
        self.btn_long = QPushButton("  LONG")
        self.btn_long.setObjectName("btnLong")
        self.btn_long.setMinimumHeight(40)
        self.btn_long.clicked.connect(self._manual_long)

        self.btn_short = QPushButton(" SHORT")
        self.btn_short.setObjectName("btnShort")
        self.btn_short.setMinimumHeight(40)
        self.btn_short.clicked.connect(self._manual_short)

        btn_layout.addWidget(self.btn_long)
        btn_layout.addWidget(self.btn_short)
        layout.addLayout(btn_layout)

        layout.addStretch()
        return w

    # -- Positions tab -----------------------------------------------------
    def _build_positions_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Wallet balance
        bal_layout = QHBoxLayout()
        self.lbl_balance = QLabel("Balance: —")
        self.lbl_balance.setObjectName("lblHeader")
        self.lbl_unrealised = QLabel("Unrealised P&L: —")
        bal_layout.addWidget(self.lbl_balance)
        bal_layout.addStretch()
        bal_layout.addWidget(self.lbl_unrealised)
        layout.addLayout(bal_layout)

        # Positions table
        self.tbl_positions = QTableWidget()
        self.tbl_positions.setColumnCount(8)
        self.tbl_positions.setHorizontalHeaderLabels([
            "Symbol", "Side", "Size", "Entry", "Mark", "PnL", "Leverage", "Liq Price",
        ])
        self.tbl_positions.horizontalHeader().setStretchLastSection(True)
        self.tbl_positions.setAlternatingRowColors(True)
        self.tbl_positions.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_positions.verticalHeader().setVisible(False)
        layout.addWidget(self.tbl_positions)

        # Close position button
        self.btn_close_selected = QPushButton("Close Selected Position")
        self.btn_close_selected.clicked.connect(self._close_selected_position)
        layout.addWidget(self.btn_close_selected)

        return w

    # -- History tab -------------------------------------------------------
    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Stats summary
        stats_layout = QHBoxLayout()
        self.lbl_total_trades = QLabel("Trades: 0")
        self.lbl_win_rate = QLabel("Win Rate: — %")
        self.lbl_total_pnl = QLabel("Total P&L: —")
        stats_layout.addWidget(self.lbl_total_trades)
        stats_layout.addWidget(self.lbl_win_rate)
        stats_layout.addWidget(self.lbl_total_pnl)
        layout.addLayout(stats_layout)

        # History table
        self.tbl_history = QTableWidget()
        self.tbl_history.setColumnCount(9)
        self.tbl_history.setHorizontalHeaderLabels([
            "Date", "Symbol", "Side", "Qty", "Entry", "Exit", "PnL", "PnL%", "Mode",
        ])
        self.tbl_history.horizontalHeader().setStretchLastSection(True)
        self.tbl_history.setAlternatingRowColors(True)
        self.tbl_history.verticalHeader().setVisible(False)
        layout.addWidget(self.tbl_history)

        btn_refresh = QPushButton("Refresh History")
        btn_refresh.clicked.connect(self._refresh_history)
        layout.addWidget(btn_refresh)

        return w

    # -- Log tab -----------------------------------------------------------
    def _build_log_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(2000)
        layout.addWidget(self.log_text)

        btn_clear = QPushButton("Clear Log")
        btn_clear.clicked.connect(self.log_text.clear)
        layout.addWidget(btn_clear)
        return w

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------
    def _build_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_status = QLabel("Ready")
        self.lbl_ws_status = QLabel("WS: disconnected")
        self.lbl_time = QLabel("")

        # Connection health LED + latency
        self.lbl_health = QLabel("●")
        self.lbl_health.setStyleSheet("color: #484f58; font-size: 14px;")
        self.lbl_health.setToolTip("API connection status")
        self.lbl_latency = QLabel("Latency: —")
        self.lbl_latency.setStyleSheet("font-size: 12px; color: #8b949e;")

        sb.addWidget(self.lbl_status, 1)
        sb.addPermanentWidget(self.lbl_health)
        sb.addPermanentWidget(self.lbl_latency)
        sb.addPermanentWidget(self.lbl_ws_status)
        sb.addPermanentWidget(self.lbl_time)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(
            lambda: self.lbl_time.setText(datetime.now(timezone.utc).strftime("UTC %H:%M:%S"))
        )
        self._clock_timer.start(1000)

    # ------------------------------------------------------------------
    # Hotkeys
    # ------------------------------------------------------------------
    def _build_hotkeys(self):
        QShortcut(QKeySequence("F5"), self, self._run_analysis)
        QShortcut(QKeySequence("F6"), self, lambda: self.btn_ideal.toggle())
        QShortcut(QKeySequence("F7"), self, lambda: self.btn_sound.toggle())
        QShortcut(QKeySequence("F8"), self, lambda: self.btn_enhanced.toggle())
        QShortcut(QKeySequence("Ctrl+L"), self, self._manual_long)
        QShortcut(QKeySequence("Ctrl+K"), self, self._manual_short)
        QShortcut(QKeySequence("Ctrl+M"), self, self._run_mtf_analysis)
        QShortcut(QKeySequence("Escape"), self, self._stop_auto_trade)

    def _stop_auto_trade(self):
        if self.btn_auto.isChecked():
            self.btn_auto.setChecked(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _initial_load(self):
        log.info("_initial_load  mode=%s", self._cfg.trading_mode)
        self._log("CryptoPenetratorXL started")
        self._log(f"Mode: {self._cfg.trading_mode.upper()}")
        self._run_analysis()
        self._refresh_positions()
        self._refresh_history()
        # Fetch full symbol list from Bybit in background
        self._sym_worker = SymbolFetchWorker(self.client)
        self._sym_worker.symbols_ready.connect(self._on_symbols_loaded)
        self._sym_worker.start()

    @pyqtSlot(list)
    def _on_symbols_loaded(self, symbols: list[str]):
        if symbols:
            self.cmb_symbol.set_symbols(symbols)
            log.info("_on_symbols_loaded  %d USDT pairs", len(symbols))
            self._log(f"Loaded {len(symbols)} USDT pairs from Bybit")
        else:
            log.warning("_on_symbols_loaded  empty list")
        # Cleanup sym_worker now that it's done
        self._cleanup_worker('_sym_worker')

    def _on_symbol_changed(self, text: str):
        self._current_symbol = text.strip().upper()
        log.info("_on_symbol_changed  → %s", self._current_symbol)
        self._persist_session()
        self._run_analysis()

    def _on_tf_changed(self, index: int):
        self._current_tf = self.cmb_tf.currentData()
        log.info("_on_tf_changed  → %s", self._current_tf)
        self._persist_session()
        self._run_analysis()

    def _on_refresh_timer(self):
        if self._auto_worker is None:
            log.debug("_on_refresh_timer  → triggering analysis")
            self._run_analysis()

    def _fast_price_update(self):
        """Fetch and display the latest price every few seconds (fast ticker).

        Updates only the price label and the last candle on the chart data,
        keeping the UI responsive without running a full analysis.
        """
        symbol = self._current_symbol
        if not symbol:
            return
        try:
            ticker = self.client.get_ticker(symbol)
            last_price = float(ticker.get("lastPrice", 0))
            if last_price <= 0:
                return
            tick = self.client.get_tick_size(symbol)
            self.lbl_price.setText(fmt_price(last_price, tick_size=tick))
            # Update current price line on chart if data is available
            if self._current_df is not None and not self._current_df.empty:
                last_idx = self._current_df.index[-1]
                # Update close price of last row to reflect the latest tick
                self._current_df.loc[last_idx, "close"] = last_price
                # Update high/low if price exceeds
                cur_high = float(self._current_df.loc[last_idx, "high"])
                cur_low = float(self._current_df.loc[last_idx, "low"])
                if last_price > cur_high:
                    self._current_df.loc[last_idx, "high"] = last_price
                if last_price < cur_low:
                    self._current_df.loc[last_idx, "low"] = last_price
        except Exception:
            pass  # Non-critical — full analysis will catch up

    # ------------------------------------------------------------------
    # Worker lifecycle helpers
    # ------------------------------------------------------------------
    def _cleanup_worker(self, attr_name: str) -> None:
        """Synchronously wait for a worker to finish, then discard it.
        
        IMPORTANT: This must be called from the main thread and NEVER
        from a QThread.finished lambda with an attribute-name lookup
        (which caused the original crash — the attribute may now point
        to a *different*, still-running worker).
        """
        worker = getattr(self, attr_name, None)
        if worker is None:
            return
        log.debug("_cleanup_worker(%s)  running=%s", attr_name, worker.isRunning())
        if worker.isRunning():
            worker.quit()
            worker.wait(3000)
        try:
            worker.disconnect()
        except Exception:
            pass
        worker.deleteLater()
        setattr(self, attr_name, None)
        log.debug("_cleanup_worker(%s)  → cleaned", attr_name)

    # ------------------------------------------------------------------
    # Analysis  (debounced)
    # ------------------------------------------------------------------
    def _run_analysis(self):
        """Schedule analysis via debounce timer (300ms)."""
        self._debounce_timer.start()  # restarts the timer if already running

    def _do_analysis(self):
        """Actually run the analysis worker — only called from debounce timer."""
        symbol = self._current_symbol
        tf = self._current_tf
        if not symbol:
            log.debug("_do_analysis  skipped — no symbol")
            return

        log.info("_do_analysis  symbol=%s  tf=%s", symbol, tf)
        self.lbl_status.setText(f"Analysing {symbol}...")
        self.btn_analyse.setEnabled(False)

        # Synchronously clean up the previous worker
        self._cleanup_worker('_analysis_worker')

        worker = AnalysisWorker(self.generator, symbol, tf)
        worker.result_ready.connect(self._on_analysis_done)
        worker.error.connect(self._on_analysis_error)
        self._analysis_worker = worker
        worker.start()

    @pyqtSlot(object, object)
    def _on_analysis_done(self, signal: TradeSignal, df):
        self.btn_analyse.setEnabled(True)
        if signal is None:
            log.warning("_on_analysis_done  signal=None")
            self.lbl_status.setText("Analysis returned no signal")
            return

        log.info(
            "_on_analysis_done  %s  signal=%s  conf=%.2f  entry=%.4f  tp=%.4f",
            signal.symbol, signal.signal.value, signal.confidence,
            signal.entry_price, signal.take_profit,
        )

        self._last_signal = signal
        self._current_df = df
        self.lbl_status.setText(f"Analysis complete: {signal.signal.value}")

        # Record signal in history (for chart markers)
        if df is not None and not df.empty and signal.signal != Signal.HOLD:
            self._signal_history.append({
                "timestamp": df["timestamp"].iloc[-1] if "timestamp" in df.columns else datetime.now(timezone.utc),
                "price": signal.entry_price,
                "signal": signal.signal,
            })
            # Keep last 50
            if len(self._signal_history) > 50:
                self._signal_history = self._signal_history[-50:]

        # Sound alert on actionable signals
        if self._sound_enabled and signal.signal in (
            Signal.STRONG_BUY, Signal.BUY, Signal.STRONG_SELL, Signal.SELL,
        ):
            try:
                freq = 900 if signal.signal in (Signal.STRONG_BUY, Signal.BUY) else 600
                winsound.Beep(freq, 150)
            except Exception:
                pass

        # Update price (tick-size-aware precision)
        if signal.entry_price:
            tick = self.client.get_tick_size(signal.symbol)
            self.chart.set_tick_size(tick)
            self.lbl_price.setText(fmt_price(signal.entry_price, tick_size=tick))
            pct = signal.indicator_detail.get("price_change_pct", 0)
            self.lbl_change.setText(fmt_pct(pct))
            if pct >= 0:
                self.lbl_change.setObjectName("lblPositive")
            else:
                self.lbl_change.setObjectName("lblNegative")
            self.lbl_change.setStyle(self.lbl_change.style())

        # Update chart (with signal markers)
        if df is not None and not df.empty:
            tf_label = ""
            for tf in Timeframe:
                if tf.value == self._current_tf:
                    tf_label = tf.label
                    break
            self.chart.set_signal_markers(self._signal_history)
            self.chart.update_chart(df, self._current_symbol, tf_label)

        # Update signal panel + risk calculator
        self._update_signal_panel(signal)
        self._update_risk_calculator(signal)

        tp_str = f"{signal.tp_pct:.2f}%" if signal.tp_pct > 0 else "—"
        self._log(
            f"[{signal.symbol}] {signal.signal.value} | "
            f"Conf: {signal.confidence:.2f} | "
            f"TP: {tp_str}"
        )

        # Trigger MTF background analysis
        self._run_mtf_analysis()

        # Trigger enhanced analysis if mode is ON
        if self._enhanced_mode and df is not None and not df.empty:
            self._run_enhanced_analysis(df)

    @pyqtSlot(str)
    def _on_analysis_error(self, err: str):
        self.btn_analyse.setEnabled(True)
        log.error("_on_analysis_error: %s", err)
        self.lbl_status.setText(f"Error: {err[:80]}")
        self._log(f"ERROR: {err}")

    # ------------------------------------------------------------------
    # Signal panel update
    # ------------------------------------------------------------------
    def _update_signal_panel(self, s: TradeSignal):
        # Signal label
        sig_text = s.signal.value
        if s.signal in (Signal.STRONG_BUY, Signal.BUY):
            self.lbl_signal.setText(f"  {sig_text}")
            self.lbl_signal.setObjectName("lblSignalBuy")
        elif s.signal in (Signal.STRONG_SELL, Signal.SELL):
            self.lbl_signal.setText(f"  {sig_text}")
            self.lbl_signal.setObjectName("lblSignalSell")
        else:
            self.lbl_signal.setText(f"  {sig_text}")
            self.lbl_signal.setObjectName("lblSignalHold")
        self.lbl_signal.setStyle(self.lbl_signal.style())

        # Confidence
        self.bar_confidence.setValue(int(s.confidence * 100))

        # Indicator scores
        detail = s.indicator_detail
        vol = detail.get("volume", {})
        stoch = detail.get("stochastic", {})
        macd = detail.get("macd", {})
        cci = detail.get("cci", {})

        self.lbl_vol_score.setText(
            f"Score: {vol.get('score', 0):+.2f}  |  Ratio: {vol.get('vol_ratio', 0):.1f}  |  "
            f"OBV: {'↑' if vol.get('obv_trend', 0) > 0 else '↓' if vol.get('obv_trend', 0) < 0 else '→'}"
        )
        self.lbl_stoch_score.setText(
            f"Score: {stoch.get('score', 0):+.2f}  |  K: {stoch.get('k', 0):.1f}  D: {stoch.get('d', 0):.1f}  |  "
            f"{stoch.get('zone', 'neutral').upper()}"
            + (f"  |  {stoch.get('crossover', '').upper()}" if stoch.get('crossover') else "")
        )
        self.lbl_macd_score.setText(
            f"Score: {macd.get('score', 0):+.2f}  |  Hist: {macd.get('histogram_direction', '')}  |  "
            f"{'Above' if macd.get('above_zero') else 'Below'} zero"
            + (f"  |  {macd.get('crossover', '').upper()}" if macd.get('crossover') else "")
        )
        self.lbl_cci_score.setText(
            f"Score: {cci.get('score', 0):+.2f}  |  CCI: {cci.get('cci', 0):.1f}  |  "
            f"{cci.get('zone', 'neutral').upper()}  |  Trend: {cci.get('trend', 'neutral')}"
        )
        self.lbl_confluence.setText(f"{detail.get('confluence_score', 0):+.4f}")
        self.lbl_candle.setText(s.candle_pattern or "—")

        # Trade setup (use tick-size-aware formatting for current symbol)
        tick = self.client.get_tick_size(s.symbol) if s.symbol else 0.0
        self.lbl_entry.setText(fmt_price(s.entry_price, tick_size=tick) if s.entry_price else "—")
        if self._cfg.use_stop_loss and s.stop_loss > 0:
            self.lbl_sl.setText(fmt_price(s.stop_loss, tick_size=tick))
            self.lbl_sl.setStyleSheet("")
        else:
            self.lbl_sl.setText("Disabled (hold through drawdown)")
            self.lbl_sl.setStyleSheet("color: #e3b341;")
        self.lbl_tp.setText(f"{fmt_price(s.take_profit, tick_size=tick)}  ({s.tp_pct:.2f}%)" if s.take_profit else "—")
        # Net TP after round-trip fees
        fee_rt = self._cfg.exchange_fee_pct * 2 * 100
        net_pct = s.tp_pct - fee_rt
        self.lbl_tp_net.setText(f"{net_pct:.3f}% (fees: {fee_rt:.3f}%)")
        if net_pct > 0:
            self.lbl_tp_net.setStyleSheet("color: #3fb950; font-weight: bold;")
        else:
            self.lbl_tp_net.setStyleSheet("color: #f85149;")
        self.lbl_leverage.setText(f"x{s.leverage:.1f}")
        self.lbl_equity.setText("100% equity × leverage" if self._cfg.use_full_balance else "—")

    # ------------------------------------------------------------------
    # Risk Calculator
    # ------------------------------------------------------------------
    def _update_risk_calculator(self, s: TradeSignal):
        """Compute and display position size, potential profit, liq distance, R/R."""
        if not s.entry_price or s.signal == Signal.HOLD:
            self.lbl_risk_position.setText("—")
            self.lbl_risk_profit.setText("—")
            self.lbl_risk_liq_dist.setText("—")
            self.lbl_risk_rr.setText("—")
            return

        # Use cached equity (updated by _refresh_positions every 15s)
        equity = self._cached_equity

        leverage = s.leverage or self._cfg.default_leverage
        position_usd = equity * leverage
        self.lbl_risk_position.setText(f"${position_usd:,.2f}")

        # Profit at TP
        fee_rt = self._cfg.exchange_fee_pct * 2  # round-trip
        if s.take_profit and s.entry_price:
            tp_pct_raw = abs(s.take_profit - s.entry_price) / s.entry_price
            net_pct = tp_pct_raw - fee_rt
            profit = position_usd * net_pct
            self.lbl_risk_profit.setText(
                f"${profit:+,.2f}  ({net_pct * 100:+.3f}%)"
            )
            if profit > 0:
                self.lbl_risk_profit.setStyleSheet("color: #3fb950; font-weight: bold;")
            else:
                self.lbl_risk_profit.setStyleSheet("color: #f85149;")
        else:
            self.lbl_risk_profit.setText("—")
            self.lbl_risk_profit.setStyleSheet("")

        # Liquidation distance
        if leverage > 0 and s.entry_price:
            # Approximate: liq = entry ± entry / leverage (simplified)
            liq_dist_pct = (1 / leverage) * 100
            self.lbl_risk_liq_dist.setText(f"~{liq_dist_pct:.1f}% from entry")
            if liq_dist_pct < 10:
                self.lbl_risk_liq_dist.setStyleSheet("color: #f85149;")
            elif liq_dist_pct < 25:
                self.lbl_risk_liq_dist.setStyleSheet("color: #e3b341;")
            else:
                self.lbl_risk_liq_dist.setStyleSheet("color: #3fb950;")
        else:
            self.lbl_risk_liq_dist.setText("—")

        # Risk/Reward — no SL means "infinite risk" in theory
        if self._cfg.use_stop_loss and s.stop_loss > 0 and s.take_profit and s.entry_price:
            risk = abs(s.entry_price - s.stop_loss)
            reward = abs(s.take_profit - s.entry_price)
            rr = reward / risk if risk > 0 else 0
            self.lbl_risk_rr.setText(f"1 : {rr:.2f}")
        else:
            self.lbl_risk_rr.setText("No SL → hold through drawdown")
            self.lbl_risk_rr.setStyleSheet("color: #e3b341;")

    # ------------------------------------------------------------------
    # Ideal Scenario toggle
    # ------------------------------------------------------------------
    def _toggle_ideal_scenario(self, checked: bool):
        self.chart.toggle_ideal_scenario(checked)
        if self._current_df is not None and not self._current_df.empty:
            tf_label = ""
            for tf in Timeframe:
                if tf.value == self._current_tf:
                    tf_label = tf.label
                    break
            self.chart.update_chart(self._current_df, self._current_symbol, tf_label)
        self._log(f"Ideal Scenario: {'ON' if checked else 'OFF'}")

    # ------------------------------------------------------------------
    # Multi-Timeframe Confluence
    # ------------------------------------------------------------------
    def _run_mtf_analysis(self):
        symbol = self._current_symbol
        if not symbol:
            return
        # Don't overlap MTF workers
        if self._mtf_worker is not None and self._mtf_worker.isRunning():
            return

        # Clean up previous finished worker
        self._cleanup_worker('_mtf_worker')

        tfs = ["5", "15", "60", "240"]  # 5m, 15m, 1h, 4h
        self._mtf_worker = MTFWorker(self.generator, symbol, tfs)
        self._mtf_worker.result_ready.connect(self._on_mtf_done)
        self._mtf_worker.start()

    @pyqtSlot(dict)
    def _on_mtf_done(self, results: dict):
        _sig_style = {
            "STRONG_BUY": "color: #3fb950; font-weight: bold;",
            "BUY": "color: #3fb950;",
            "HOLD": "color: #d29922;",
            "SELL": "color: #f85149;",
            "STRONG_SELL": "color: #f85149; font-weight: bold;",
            "ERR": "color: #484f58;",
        }
        _map = {"5": self.lbl_mtf_5m, "15": self.lbl_mtf_15m,
                "60": self.lbl_mtf_1h, "240": self.lbl_mtf_4h}
        for tf_val, lbl in _map.items():
            data = results.get(tf_val, {})
            sig = data.get("signal", "ERR")
            conf = data.get("confidence", 0)
            txt = f"{sig}  (conf: {conf:.2f})"
            lbl.setText(txt)
            lbl.setStyleSheet(_sig_style.get(sig, ""))

    # ------------------------------------------------------------------
    # Connection Health + Latency  (background worker)
    # ------------------------------------------------------------------
    def _update_latency(self):
        """Launch background worker to ping Bybit server time."""
        # Skip if a latency worker is already running
        if self._latency_worker is not None and self._latency_worker.isRunning():
            return
        self._cleanup_worker('_latency_worker')

        worker = LatencyWorker(self.client)
        worker.result_ready.connect(self._on_latency_done)
        worker.error.connect(self._on_latency_error)
        self._latency_worker = worker
        worker.start()

    @pyqtSlot(float)
    def _on_latency_done(self, ms: float):
        self.lbl_latency.setText(f"Latency: {ms:.0f}ms")
        if ms < 300:
            self.lbl_health.setStyleSheet("color: #3fb950; font-size: 14px;")
            self.lbl_health.setToolTip(f"API OK — {ms:.0f}ms")
        elif ms < 800:
            self.lbl_health.setStyleSheet("color: #e3b341; font-size: 14px;")
            self.lbl_health.setToolTip(f"API Slow — {ms:.0f}ms")
        else:
            self.lbl_health.setStyleSheet("color: #f85149; font-size: 14px;")
            self.lbl_health.setToolTip(f"API Degraded — {ms:.0f}ms")

    @pyqtSlot(str)
    def _on_latency_error(self, _err: str):
        self.lbl_latency.setText("Latency: ERR")
        self.lbl_health.setStyleSheet("color: #f85149; font-size: 14px;")
        self.lbl_health.setToolTip("API unreachable")

    # ------------------------------------------------------------------
    # Manual trading
    # ------------------------------------------------------------------
    def _manual_long(self):
        self._manual_trade(Side.LONG)

    def _manual_short(self):
        self._manual_trade(Side.SHORT)

    def _manual_trade(self, side: Side):
        log.info("_manual_trade  side=%s", side.value)
        if self._last_signal is None:
            log.warning("_manual_trade  no signal available")
            self._log("Run analysis first before placing a trade")
            return

        signal = self._last_signal
        # Override signal direction
        signal_copy = TradeSignal(
            symbol=signal.symbol,
            signal=Signal.STRONG_BUY if side == Side.LONG else Signal.STRONG_SELL,
            side=side,
            confidence=max(signal.confidence, 0.5),
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            leverage=signal.leverage,
            timeframe=signal.timeframe,
            indicator_detail=signal.indicator_detail,
            notes=f"Manual {side.value}",
        )

        # Confirm if live
        if self.executor.is_live:
            reply = QMessageBox.question(
                self, "Confirm LIVE Trade",
                f"Place a LIVE {side.value} order on {signal.symbol}?\n"
                f"Full-balance position with x{signal.leverage} leverage.\n"
                f"TP: {fmt_price(signal.take_profit, tick_size=self.client.get_tick_size(signal.symbol))}  |  SL: {'DISABLED' if not self._cfg.use_stop_loss else fmt_price(signal.stop_loss, tick_size=self.client.get_tick_size(signal.symbol))}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        result = self.executor.execute(signal_copy)
        self._log(f"Manual {side.value}: {result.get('status')} — {result}")
        if result.get("status") in ("filled", "paper_filled"):
            if result.get("mode") == "paper":
                self.paper_manager.open(result)
            db.save_trade(result)
        self._update_last_trade_label(result)
        self._refresh_positions()

    # ------------------------------------------------------------------
    # Auto-trade
    # ------------------------------------------------------------------
    def _toggle_auto_trade(self, checked: bool):
        log.info("_toggle_auto_trade  checked=%s", checked)
        if checked:
            # Confirm in LIVE mode
            if self.executor.is_live:
                reply = QMessageBox.warning(
                    self, "Confirm LIVE Auto-Trade",
                    f"You are about to start AUTO-TRADE in LIVE mode!\n\n"
                    f"Symbol: {self._current_symbol}\n"
                    f"Timeframe: {self._current_tf}m\n"
                    f"Interval: {self._cfg.monitor_interval_sec}s\n\n"
                    "Real orders will be placed on Bybit.\nContinue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    self.btn_auto.blockSignals(True)
                    self.btn_auto.setChecked(False)
                    self.btn_auto.blockSignals(False)
                    return

            self.btn_auto.setText("  STOP AUTO")
            symbol = self._current_symbol
            tf = self._current_tf
            interval = self._cfg.monitor_interval_sec

            self._auto_worker = AutoTradeWorker(
                self.generator, self.executor, self.paper_manager,
                symbol, tf, interval,
            )
            self._auto_worker.signal_generated.connect(self._on_auto_signal)
            self._auto_worker.chart_data_ready.connect(self._on_auto_chart_data)
            self._auto_worker.trade_executed.connect(self._on_auto_trade)
            self._auto_worker.trade_closed.connect(self._on_auto_trade_closed)
            self._auto_worker.position_update.connect(self._on_auto_position_update)
            self._auto_worker.log_message.connect(self._log)
            self._auto_worker.countdown.connect(self._on_auto_countdown)
            self._auto_worker.error.connect(lambda e: self._log(f"AUTO ERROR: {e}"))
            self._auto_worker.start()
            self.lbl_status.setText(f"Auto-trading {symbol} / {tf}m")
            self._log(f"Auto-trading STARTED  [{symbol} / {tf}m]")
            # Lock symbol/TF combos while auto-trading
            self.cmb_symbol.setEnabled(False)
            self.cmb_tf.setEnabled(False)
        else:
            self.btn_auto.setText("  AUTO TRADE")
            if self._auto_worker:
                self._auto_worker.stop()
                self._auto_worker.wait(5000)
                self._auto_worker = None
            self.lbl_status.setText("Ready")
            self._log("Auto-trading STOPPED")
            # Unlock symbol/TF combos
            self.cmb_symbol.setEnabled(True)
            self.cmb_tf.setEnabled(True)

    @pyqtSlot(int)
    def _on_auto_countdown(self, remaining: int):
        """Update AUTO button text with countdown."""
        if remaining > 0:
            self.btn_auto.setText(f"  STOP ({remaining}s)")
        else:
            self.btn_auto.setText("  STOP AUTO")

    @pyqtSlot(object)
    def _on_auto_signal(self, signal: TradeSignal):
        if signal.symbol == self._current_symbol:
            self._update_signal_panel(signal)

    @pyqtSlot(object, object)
    def _on_auto_chart_data(self, signal: TradeSignal, df):
        """Update the chart with fresh data from auto-trade analysis cycle."""
        if signal.symbol != self._current_symbol:
            return
        if df is None or (hasattr(df, 'empty') and df.empty):
            return
        # Update displayed price with tick-size precision
        if signal.entry_price:
            tick = self.client.get_tick_size(signal.symbol)
            self.chart.set_tick_size(tick)
            self.lbl_price.setText(fmt_price(signal.entry_price, tick_size=tick))
            pct = signal.indicator_detail.get("price_change_pct", 0)
            self.lbl_change.setText(fmt_pct(pct))
            if pct >= 0:
                self.lbl_change.setObjectName("lblPositive")
            else:
                self.lbl_change.setObjectName("lblNegative")
            self.lbl_change.setStyle(self.lbl_change.style())
        # Update chart
        tf_label = ""
        for tf in Timeframe:
            if tf.value == self._current_tf:
                tf_label = tf.label
                break
        self.chart.set_signal_markers(self._signal_history)
        self.chart.update_chart(df, self._current_symbol, tf_label)

    @pyqtSlot(object)
    def _on_auto_trade(self, result: dict):
        status = result.get("status", "?")
        symbol = result.get("symbol", "?")
        side = result.get("side", "?")
        entry = result.get("entry_price", 0)
        tp = result.get("take_profit", 0)
        lev = result.get("leverage", "?")
        if status in ("filled", "paper_filled"):
            self._log(f"AUTO TRADE: {status} {side} {symbol}  entry={fmt_price(entry)}  TP={fmt_price(tp)}  x{lev}")
            # Success sound
            if self._sound_enabled:
                try:
                    winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
                except Exception:
                    pass
        else:
            reason = result.get("reason", status)
            self._log(f"AUTO TRADE: rejected {side} {symbol} — {reason}")
            if self._sound_enabled:
                try:
                    winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
                except Exception:
                    pass
        self._refresh_positions()
        # Update last-trade label
        self._update_last_trade_label(result)
        # Feed to analytics
        if hasattr(self, "analytics_widget"):
            self.analytics_widget.record_trade(result)
        # Update chart trade overlay for new position
        if status in ("filled", "paper_filled"):
            pos = self.paper_manager.get_position(symbol)
            self.chart.set_active_trade(pos)

    @pyqtSlot(object)
    def _on_auto_trade_closed(self, closed: dict):
        """Handle auto-close of a paper position (TP hit)."""
        symbol = closed.get("symbol", "?")
        side = closed.get("side", "?")
        pnl = closed.get("pnl", 0)
        pnl_pct = closed.get("pnl_pct", 0)
        self._log(
            f"AUTO CLOSE (TP): {side} {symbol}  PnL=${pnl:+.2f} ({pnl_pct:+.2f}%)"
        )
        if self._sound_enabled:
            try:
                winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass
        self._refresh_positions()
        self._refresh_history()
        # Remove chart trade overlay
        self.chart.set_active_trade(None)

    @pyqtSlot(object)
    def _on_auto_position_update(self, pos: dict):
        """Refresh chart overlay with latest mark price from auto-trade monitor."""
        if pos.get("symbol") == self._current_symbol:
            self.chart.set_active_trade(pos)

    @pyqtSlot(object)
    def _on_position_tp_closed(self, closed: dict):
        """Handle TP-close coming from PositionsWorker (background refresh)."""
        self._on_auto_trade_closed(closed)

    # ------------------------------------------------------------------
    # Last Trade label helper
    # ------------------------------------------------------------------
    def _update_last_trade_label(self, result: dict):
        """Update the 'Last Trade' label on signal tab."""
        status = result.get("status", "?")
        symbol = result.get("symbol", "?")
        side = result.get("side", "?")
        ts = result.get("timestamp", "")
        if ts:
            # Show just time portion
            ts = ts.split("T")[-1][:8] if "T" in ts else ts[:8]
        if status in ("filled", "paper_filled"):
            entry = result.get("entry_price", 0)
            tp = result.get("take_profit", 0)
            mode = "LIVE" if status == "filled" else "PAPER"
            color = "#3fb950" if side in ("Buy", "LONG") else "#f85149"
            self.lbl_last_trade.setText(
                f"{side} {symbol} @ {fmt_price(entry)}\n"
                f"TP: {fmt_price(tp)}  |  {mode}  |  {ts}"
            )
            self.lbl_last_trade.setStyleSheet(f"color: {color}; font-weight: bold;")
        else:
            reason = result.get("reason", status)
            self.lbl_last_trade.setText(f"Rejected: {symbol} — {reason}")
            self.lbl_last_trade.setStyleSheet("color: #e3b341;")

    # ------------------------------------------------------------------
    # Positions  (background worker to avoid blocking UI)
    # ------------------------------------------------------------------
    def _refresh_positions(self):
        """Launch a background worker to fetch wallet + positions."""
        # Skip if a positions worker is already running
        if self._positions_worker is not None and self._positions_worker.isRunning():
            log.debug("_refresh_positions  skipped — worker still running")
            return
        self._cleanup_worker('_positions_worker')
        log.debug("_refresh_positions  launching PositionsWorker")

        is_paper = self._cfg.trading_mode == "paper"
        worker = PositionsWorker(
            self.client,
            paper_mode=is_paper,
            paper_manager=self.paper_manager if is_paper else None,
        )
        worker.result_ready.connect(self._on_positions_done)
        worker.trade_closed.connect(self._on_position_tp_closed)
        worker.error.connect(self._on_positions_error)
        self._positions_worker = worker
        worker.start()

    @pyqtSlot(dict, list)
    def _on_positions_done(self, wallet: dict, positions: list):
        """Update UI from background positions data."""
        equity = wallet["equity"]
        self._cached_equity = equity
        log.debug(
            "_on_positions_done  equity=$%.2f  uPnL=$%.2f  positions=%d",
            equity, wallet["unrealised_pnl"], len(positions),
        )
        suffix = " (PAPER)" if self._cfg.trading_mode == "paper" else ""
        self.lbl_balance.setText(f"Balance: ${equity:,.2f}{suffix}")
        upnl = wallet["unrealised_pnl"]
        color = "#3fb950" if upnl >= 0 else "#f85149"
        self.lbl_unrealised.setText(f"Unrealised P&L: ${upnl:+,.2f}")
        self.lbl_unrealised.setStyleSheet(f"color: {color}; font-weight: bold;")

        # Positions table
        self.tbl_positions.setRowCount(len(positions))
        for i, p in enumerate(positions):
            sym = p["symbol"]
            tick = self.client.get_tick_size(sym)
            self.tbl_positions.setItem(i, 0, QTableWidgetItem(sym))
            side_item = QTableWidgetItem(p["side"])
            side_item.setForeground(QColor(BULL_COLOR if p["side"] == "Buy" else BEAR_COLOR))
            self.tbl_positions.setItem(i, 1, side_item)
            self.tbl_positions.setItem(i, 2, QTableWidgetItem(fmt_qty(p["size"])))
            self.tbl_positions.setItem(i, 3, QTableWidgetItem(fmt_price(p["entry_price"], tick_size=tick)))
            self.tbl_positions.setItem(i, 4, QTableWidgetItem(fmt_price(p["mark_price"], tick_size=tick)))

            pnl = p["unrealised_pnl"]
            pnl_item = QTableWidgetItem(f"${pnl:+,.2f}")
            pnl_item.setForeground(QColor("#3fb950" if pnl >= 0 else "#f85149"))
            self.tbl_positions.setItem(i, 5, pnl_item)
            self.tbl_positions.setItem(i, 6, QTableWidgetItem(str(p["leverage"])))
            self.tbl_positions.setItem(i, 7, QTableWidgetItem(
                fmt_price(p["liq_price"], tick_size=tick) if p["liq_price"] else "—"
            ))

        # Update chart trade overlay for current symbol
        if self._show_trade_overlay:
            active = next(
                (p for p in positions if p["symbol"] == self._current_symbol), None
            )
            self.chart.set_active_trade(active)
        else:
            self.chart.set_active_trade(None)

    @pyqtSlot(str)
    def _on_positions_error(self, err: str):
        err_key = err.split(":")[0] if ":" in err else err[:30]
        if not hasattr(self, '_last_pos_err') or self._last_pos_err != err_key:
            self._last_pos_err = err_key
            self._log(f"Positions unavailable: {err}")
        self.lbl_balance.setText("Balance: unavailable")
        self.lbl_unrealised.setText("Unrealised P&L: —")
        self.tbl_positions.setRowCount(0)

    def _close_selected_position(self):
        row = self.tbl_positions.currentRow()
        if row < 0:
            self._log("Select a position to close")
            return
        symbol = self.tbl_positions.item(row, 0).text()
        side_text = self.tbl_positions.item(row, 1).text()
        size = float(self.tbl_positions.item(row, 2).text().replace(",", ""))
        side = Side.LONG if side_text == "Buy" else Side.SHORT
        log.info("_close_selected_position  %s %s  size=%.6f", side.value, symbol, size)

        # Paper position — close via paper_manager
        if self.paper_manager.has_position(symbol):
            pos = self.paper_manager.get_position(symbol)
            mark = pos["mark_price"] if pos else 0
            reply = QMessageBox.question(
                self, "Close Paper Position",
                f"Close {side_text} {symbol}?\n"
                f"Entry: {fmt_price(pos['entry_price'])}  |  Mark: {fmt_price(mark)}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            closed = self.paper_manager.close(symbol, mark)
            if closed:
                db.close_trade(closed["order_id"], mark, closed["pnl"], closed["pnl_pct"])
                self._log(
                    f"CLOSED {side_text} {symbol}  exit={fmt_price(mark)}  "
                    f"PnL=${closed['pnl']:+.2f} ({closed['pnl_pct']:+.2f}%)"
                )
                if self._sound_enabled:
                    try:
                        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
                    except Exception:
                        pass
            self._refresh_positions()
            self._refresh_history()
            # Update chart trade overlay
            self.chart.set_active_trade(None)
            return

        # Live position — close via executor
        if self.executor.is_live:
            reply = QMessageBox.question(
                self, "Close Position",
                f"Close {side_text} {symbol} (size={size})?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        result = self.executor.close_position(symbol, side, size)
        self._log(f"Close position: {result}")
        self._refresh_positions()

    def _close_all_positions(self):
        log.info("_close_all_positions called")
        try:
            # Close paper positions first
            paper_positions = self.paper_manager.get_positions()
            if paper_positions:
                reply = QMessageBox.question(
                    self, "Close ALL Paper Positions",
                    f"Close all {len(paper_positions)} paper positions?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    for p in paper_positions:
                        closed = self.paper_manager.close(p["symbol"], p["mark_price"])
                        if closed:
                            db.close_trade(closed["order_id"], p["mark_price"],
                                           closed["pnl"], closed["pnl_pct"])
                            self._log(f"Closed paper {p['side']} {p['symbol']}  PnL=${closed['pnl']:+.2f}")
                    self.chart.set_active_trade(None)

            # Close live positions
            positions = self.client.get_positions()
            if positions:
                if self.executor.is_live:
                    reply = QMessageBox.question(
                        self, "Close ALL Positions",
                        f"Close all {len(positions)} live positions?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        self._refresh_positions()
                        return
                for p in positions:
                    side = Side.LONG if p["side"] == "Buy" else Side.SHORT
                    self.executor.close_position(p["symbol"], side, p["size"])
                    self._log(f"Closed {p['side']} {p['symbol']}")

            if not paper_positions and not positions:
                self._log("No open positions")

            self._refresh_positions()
            self._refresh_history()
        except Exception as e:
            self._log(f"Close all error: {e}")

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def _refresh_history(self):
        try:
            current_mode = self._cfg.trading_mode
            trades = db.get_trade_history(100, mode=current_mode)
            self.tbl_history.setRowCount(len(trades))
            for i, t in enumerate(trades):
                self.tbl_history.setItem(i, 0, QTableWidgetItem(
                    t.opened_at.strftime("%Y-%m-%d %H:%M") if t.opened_at else ""
                ))
                self.tbl_history.setItem(i, 1, QTableWidgetItem(t.symbol))
                self.tbl_history.setItem(i, 2, QTableWidgetItem(t.side))
                self.tbl_history.setItem(i, 3, QTableWidgetItem(fmt_qty(t.qty)))
                self.tbl_history.setItem(i, 4, QTableWidgetItem(fmt_price(t.entry_price)))
                self.tbl_history.setItem(i, 5, QTableWidgetItem(
                    fmt_price(t.exit_price) if t.exit_price else "—"
                ))
                pnl_text = f"${t.pnl:+,.2f}" if t.pnl is not None else "—"
                pnl_item = QTableWidgetItem(pnl_text)
                if t.pnl is not None:
                    pnl_item.setForeground(QColor("#3fb950" if t.pnl >= 0 else "#f85149"))
                self.tbl_history.setItem(i, 6, pnl_item)
                self.tbl_history.setItem(i, 7, QTableWidgetItem(
                    f"{t.pnl_pct:+.2f}%" if t.pnl_pct is not None else "—"
                ))
                self.tbl_history.setItem(i, 8, QTableWidgetItem(t.mode or ""))

            # Stats
            stats = db.get_trade_stats(mode=current_mode)
            self.lbl_total_trades.setText(f"Trades: {stats['total']}")
            self.lbl_win_rate.setText(f"Win Rate: {stats['win_rate']}%")
            total_pnl = stats["total_pnl"]
            color = "#3fb950" if total_pnl >= 0 else "#f85149"
            self.lbl_total_pnl.setText(f"Total P&L: ${total_pnl:+,.2f}")
            self.lbl_total_pnl.setStyleSheet(f"color: {color}; font-weight: bold;")

        except Exception as e:
            self._log(f"History refresh error: {e}")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def _persist_session(self):
        """Save current UI session state to disk."""
        _save_session_state({
            "symbol": self._current_symbol,
            "timeframe": self._current_tf,
            "show_trade_overlay": self._show_trade_overlay,
            "crosshair_enabled": self._crosshair_enabled,
        })

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_vals = dlg.get_values()
            overlay_pref = dlg.get_overlay_pref()
            crosshair_pref = dlg.get_crosshair_pref()
            # Write changes to .env
            _update_env_file(new_vals)
            # Persist overlay & crosshair preferences in session state
            _ses = _load_session_state()
            _ses["show_trade_overlay"] = overlay_pref
            _ses["crosshair_enabled"] = crosshair_pref
            _save_session_state(_ses)
            self._show_trade_overlay = overlay_pref
            self._crosshair_enabled = crosshair_pref
            self.chart.toggle_crosshair(crosshair_pref)
            # Invalidate cached settings so next get_settings() re-reads .env
            get_settings.cache_clear()
            self._cfg = get_settings()
            # Re-create BybitClient so testnet / API-key changes take effect
            try:
                new_client = BybitClient()
                self.client = new_client
                self.executor.client = new_client
                self.executor.risk.client = new_client
                self.generator.client = new_client
                log.info("BybitClient re-created after settings change")
            except Exception as exc:
                log.warning("Failed to re-create BybitClient: %s", exc)
            # Apply trading mode change at runtime — update all components
            self.executor._cfg = self._cfg
            self.executor.risk._cfg = self._cfg
            # Update mode label in toolbar
            mode = self._cfg.trading_mode.upper()
            self.lbl_mode.setText(f"[{mode}]")
            self.lbl_mode.setStyleSheet(
                "color: #3fb950; font-weight: bold;" if mode == "PAPER"
                else "color: #f85149; font-weight: bold; font-size: 14px;"
            )
            self._log(f"Settings saved. Mode: {mode}")
            # Refresh balance immediately with new settings
            self._refresh_positions()

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{ts}] {msg}")
        log.info(msg)

    # ------------------------------------------------------------------
    # Enhanced Analysis mode
    # ------------------------------------------------------------------
    def _toggle_enhanced_mode(self, checked: bool):
        self._enhanced_mode = checked
        self.grp_enhanced.setVisible(checked)
        self.chart.toggle_enhanced(checked)
        if checked and self._current_df is not None and not self._current_df.empty:
            self._run_enhanced_analysis(self._current_df)
        elif not checked:
            self.chart.set_enhanced_data(None)
            # Redraw chart without enhanced overlay
            if self._current_df is not None and not self._current_df.empty:
                tf_label = ""
                for tf in Timeframe:
                    if tf.value == self._current_tf:
                        tf_label = tf.label
                        break
                self.chart.update_chart(self._current_df, self._current_symbol, tf_label)
        self._log(f"Enhanced Analysis: {'ON' if checked else 'OFF'}")

    def _run_enhanced_analysis(self, df):
        """Run enhanced analysis in a background thread."""
        log.info("_run_enhanced_analysis  rows=%d", len(df))
        self._cleanup_worker('_enhanced_worker')

        worker = EnhancedAnalysisWorker(self._enhanced_engine, df.copy())
        worker.result_ready.connect(self._on_enhanced_done)
        worker.error.connect(lambda e: self._log(f"Enhanced analysis error: {e}"))
        self._enhanced_worker = worker
        worker.start()

    @pyqtSlot(object)
    def _on_enhanced_done(self, result: EnhancedAnalysisResult):
        """Handle enhanced analysis results — update panel & chart overlay."""
        log.info(
            "_on_enhanced_done  patterns=%d  structures=%d  prob_up=%.0f%%  prob_down=%.0f%%",
            len(result.candle_patterns), len(result.structures),
            result.forecast.prob_up * 100, result.forecast.prob_down * 100,
        )
        # Update panel labels
        if result.candle_patterns:
            pat_lines = []
            for p in result.candle_patterns[-5:]:   # show last 5
                icon = "🟢" if p.kind == "bullish" else "🔴" if p.kind == "bearish" else "⚪"
                pat_lines.append(f"{icon} {p.name} ({p.confidence:.0%})")
            self.lbl_enh_patterns.setText("\n".join(pat_lines))
        else:
            self.lbl_enh_patterns.setText("No patterns detected")

        if result.structures:
            str_lines = []
            for s in result.structures[:4]:
                icon = "🟢" if s.kind == "bullish" else "🔴" if s.kind == "bearish" else "⚪"
                str_lines.append(f"{icon} {s.name} ({s.confidence:.0%})")
            self.lbl_enh_structures.setText("\n".join(str_lines))
        else:
            self.lbl_enh_structures.setText("No structures detected")

        # Probability bar text
        f = result.forecast
        self.lbl_enh_probability.setText(
            f"↑ {f.prob_up * 100:.0f}%  |  ↓ {f.prob_down * 100:.0f}%"
        )
        if f.prob_up > 0.55:
            self.lbl_enh_probability.setStyleSheet("color: #3fb950; font-weight: bold;")
        elif f.prob_down > 0.55:
            self.lbl_enh_probability.setStyleSheet("color: #f85149; font-weight: bold;")
        else:
            self.lbl_enh_probability.setStyleSheet("color: #d29922;")

        # Psychology
        ps = result.psych
        self.lbl_enh_psych.setText(ps.description)
        self.lbl_enh_forecast.setText(
            f"Expected: {f.expected_move_pct:+.3f}%  |  "
            f"Vol: {f.volatility_pct:.2f}%  |  "
            f"S: {f.support:,.2f}  R: {f.resistance:,.2f}"
        )

        # Pass data to chart for overlay
        self.chart.set_enhanced_data(result)
        if self._current_df is not None and not self._current_df.empty:
            tf_label = ""
            for tf in Timeframe:
                if tf.value == self._current_tf:
                    tf_label = tf.label
                    break
            self.chart.update_chart(self._current_df, self._current_symbol, tf_label)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        log.info("closeEvent  — shutting down")
        # Persist session state
        self._persist_session()
        # Stop timers
        self._debounce_timer.stop()
        self._refresh_timer.stop()
        self._positions_timer.stop()
        self._latency_timer.stop()
        self._price_ticker_timer.stop()
        self._clock_timer.stop()
        # Stop auto-trader
        if self._auto_worker:
            self._auto_worker.stop()
            self._auto_worker.wait(3000)
        # Clean up all background workers
        for attr in ('_analysis_worker', '_sym_worker', '_mtf_worker',
                      '_enhanced_worker', '_positions_worker', '_latency_worker'):
            w = getattr(self, attr, None)
            if w is not None:
                if w.isRunning():
                    w.quit()
                    w.wait(2000)
                try:
                    w.disconnect()
                except Exception:
                    pass
                w.deleteLater()
                setattr(self, attr, None)
        event.accept()


# Colour constants for table items
BULL_COLOR = "#3fb950"
BEAR_COLOR = "#f85149"
