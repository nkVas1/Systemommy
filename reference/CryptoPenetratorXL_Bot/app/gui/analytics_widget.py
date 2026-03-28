"""
CryptoPenetratorXL — Real-Time Analytics Widget  v2.1

Session-level trading analytics panel:
  • Running P&L counter
  • Trade log with timing & net %
  • Win/loss statistics
  • Session timer
  • Equity curve mini-chart (matplotlib)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from app.core.config import get_settings
from app.utils.helpers import fmt_price


# ======================================================================
# Session Trade Record
# ======================================================================
class _SessionTrade:
    """In-memory record of a single trade placed during this session."""

    __slots__ = (
        "timestamp", "symbol", "side", "qty", "entry_price",
        "take_profit", "stop_loss", "equity", "notional",
        "net_tp_pct", "status", "mode", "order_id",
    )

    def __init__(self, data: dict[str, Any]):
        self.timestamp: str = data.get("timestamp", datetime.now(timezone.utc).isoformat())
        self.symbol: str = data.get("symbol", "?")
        self.side: str = data.get("side", "?")
        self.qty: float = data.get("qty", 0)
        self.entry_price: float = data.get("entry_price", 0)
        self.take_profit: float = data.get("take_profit", 0)
        self.stop_loss: float = data.get("stop_loss", 0)
        self.equity: float = data.get("equity", 0)
        self.notional: float = data.get("notional", 0)
        self.net_tp_pct: float = data.get("net_tp_pct", 0)
        self.status: str = data.get("status", "?")
        self.mode: str = data.get("mode", "paper")
        self.order_id: str = data.get("order_id", "")


# ======================================================================
# Analytics Widget
# ======================================================================
class AnalyticsWidget(QWidget):
    """Real-time session analytics panel embedded in the main tab widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg = get_settings()
        self._session_start = datetime.now(timezone.utc)
        self._trades: list[_SessionTrade] = []
        self._pnl_history: list[float] = [0.0]  # cumulative PnL points

        self._build_ui()

        # 1-second ticker for session timer
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._update_timer)
        self._tick_timer.start(1000)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        # ---- Row 1: session stats cards ----
        stats_row = QHBoxLayout()

        self.lbl_session_time = self._make_stat_card("Session", "00:00:00")
        self.lbl_total_trades = self._make_stat_card("Trades", "0")
        self.lbl_win_rate = self._make_stat_card("Win Rate", "— %")
        self.lbl_session_pnl = self._make_stat_card("Session P&L", "$0.00")
        self.lbl_avg_profit = self._make_stat_card("Avg Profit", "— %")

        for card in (self.lbl_session_time, self.lbl_total_trades,
                     self.lbl_win_rate, self.lbl_session_pnl, self.lbl_avg_profit):
            stats_row.addWidget(card)
        root.addLayout(stats_row)

        # ---- Row 2: equity curve ----
        grp_chart = QGroupBox("Session Equity Curve")
        chart_layout = QVBoxLayout(grp_chart)
        self._fig = Figure(figsize=(5, 1.8), dpi=100)
        self._fig.patch.set_facecolor("#0d1117")
        self._ax = self._fig.add_subplot(111)
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        chart_layout.addWidget(self._canvas)
        root.addWidget(grp_chart)

        # ---- Row 3: live trades table ----
        grp_table = QGroupBox("Session Trades")
        table_layout = QVBoxLayout(grp_table)
        self.tbl_trades = QTableWidget()
        self.tbl_trades.setColumnCount(9)
        self.tbl_trades.setHorizontalHeaderLabels([
            "Time", "Symbol", "Side", "Qty", "Entry", "TP Target",
            "Net TP %", "Equity", "Status",
        ])
        self.tbl_trades.horizontalHeader().setStretchLastSection(True)
        self.tbl_trades.setAlternatingRowColors(True)
        self.tbl_trades.verticalHeader().setVisible(False)
        table_layout.addWidget(self.tbl_trades)

        btn_reset = QPushButton("Reset Session")
        btn_reset.clicked.connect(self.reset_session)
        table_layout.addWidget(btn_reset)

        root.addWidget(grp_table, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def record_trade(self, data: dict[str, Any]):
        """Called by MainWindow when a trade is executed."""
        status = data.get("status", "")
        if status not in ("filled", "paper_filled"):
            return

        trade = _SessionTrade(data)
        self._trades.append(trade)

        # Estimate session P&L (TP-based expected profit)
        expected_profit = trade.equity * (trade.net_tp_pct / 100) if trade.net_tp_pct else 0
        cumulative = self._pnl_history[-1] + expected_profit
        self._pnl_history.append(cumulative)

        self._refresh_stats()
        self._refresh_table()
        self._refresh_chart()

    def reset_session(self):
        """Reset session analytics."""
        self._session_start = datetime.now(timezone.utc)
        self._trades.clear()
        self._pnl_history = [0.0]
        self._refresh_stats()
        self._refresh_table()
        self._refresh_chart()

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------
    def _refresh_stats(self):
        n = len(self._trades)
        self._set_card_value(self.lbl_total_trades, str(n))

        if n == 0:
            self._set_card_value(self.lbl_win_rate, "— %")
            self._set_card_value(self.lbl_session_pnl, "$0.00")
            self._set_card_value(self.lbl_avg_profit, "— %")
            return

        # Expected wins = trades with positive net_tp_pct (all of them ideally)
        wins = sum(1 for t in self._trades if t.net_tp_pct > 0)
        wr = wins / n * 100
        self._set_card_value(self.lbl_win_rate, f"{wr:.1f}%")

        pnl = self._pnl_history[-1]
        color = "#3fb950" if pnl >= 0 else "#f85149"
        val_label = self.lbl_session_pnl.findChild(QLabel, "val")
        if val_label:
            val_label.setText(f"${pnl:+,.2f}")
            val_label.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: bold;")

        avg_pct = sum(t.net_tp_pct for t in self._trades) / n
        self._set_card_value(self.lbl_avg_profit, f"{avg_pct:.3f}%")

    def _refresh_table(self):
        self.tbl_trades.setRowCount(len(self._trades))
        for i, t in enumerate(self._trades):
            try:
                ts_dt = datetime.fromisoformat(t.timestamp)
                ts_str = ts_dt.strftime("%H:%M:%S")
            except Exception:
                ts_str = t.timestamp[:8]

            self.tbl_trades.setItem(i, 0, QTableWidgetItem(ts_str))
            self.tbl_trades.setItem(i, 1, QTableWidgetItem(t.symbol))

            side_item = QTableWidgetItem(t.side)
            side_item.setForeground(QColor("#3fb950" if t.side == "Buy" else "#f85149"))
            self.tbl_trades.setItem(i, 2, side_item)

            self.tbl_trades.setItem(i, 3, QTableWidgetItem(f"{t.qty:.6f}"))
            self.tbl_trades.setItem(i, 4, QTableWidgetItem(fmt_price(t.entry_price)))
            self.tbl_trades.setItem(i, 5, QTableWidgetItem(fmt_price(t.take_profit)))
            self.tbl_trades.setItem(i, 6, QTableWidgetItem(f"{t.net_tp_pct:.3f}%"))
            self.tbl_trades.setItem(i, 7, QTableWidgetItem(f"${t.equity:,.2f}"))
            self.tbl_trades.setItem(i, 8, QTableWidgetItem(t.status))

    def _refresh_chart(self):
        ax = self._ax
        ax.clear()
        ax.set_facecolor("#0d1117")

        if len(self._pnl_history) < 2:
            self._canvas.draw_idle()
            return

        x = list(range(len(self._pnl_history)))
        y = self._pnl_history

        # Fill green above 0, red below
        ax.fill_between(x, y, 0, where=[v >= 0 for v in y],
                        color="#3fb950", alpha=0.3, interpolate=True)
        ax.fill_between(x, y, 0, where=[v < 0 for v in y],
                        color="#f85149", alpha=0.3, interpolate=True)
        ax.plot(x, y, color="#58a6ff", linewidth=1.5)
        ax.axhline(0, color="#484f58", linewidth=0.5, linestyle="--")

        ax.set_ylabel("P&L ($)", color="#8b949e", fontsize=8)
        ax.tick_params(colors="#8b949e", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#30363d")

        self._fig.tight_layout(pad=0.5)
        self._canvas.draw_idle()

    def _update_timer(self):
        elapsed = datetime.now(timezone.utc) - self._session_start
        h, rem = divmod(int(elapsed.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        self._set_card_value(self.lbl_session_time, f"{h:02d}:{m:02d}:{s:02d}")

    # ------------------------------------------------------------------
    # Card helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _make_stat_card(title: str, value: str) -> QWidget:
        """Small KPI card widget."""
        card = QWidget()
        card.setStyleSheet(
            "background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 6px;"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet("color: #8b949e; font-size: 10px; border: none;")

        lbl_val = QLabel(value)
        lbl_val.setObjectName("val")
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_val.setStyleSheet("color: #c9d1d9; font-size: 16px; font-weight: bold; border: none;")

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_val)
        return card

    @staticmethod
    def _set_card_value(card: QWidget, text: str):
        lbl = card.findChild(QLabel, "val")
        if lbl:
            lbl.setText(text)
