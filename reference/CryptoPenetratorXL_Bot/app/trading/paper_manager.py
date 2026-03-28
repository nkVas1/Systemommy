"""
CryptoPenetratorXL — Paper Position Manager

Thread-safe in-memory tracker for paper-trading positions.
Provides the same position dict format as BybitClient.get_positions()
so paper positions integrate seamlessly with the Positions tab.
"""

from __future__ import annotations

import threading
from typing import Any

from app.core.logger import get_logger

log = get_logger("trading.paper")


class PaperPositionManager:
    """Thread-safe in-memory paper position tracker.

    Position dict format (matches BybitClient.get_positions output):
        symbol, side, size, entry_price, mark_price,
        unrealised_pnl, leverage, liq_price, tp, sl, order_id
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._positions: dict[str, dict[str, Any]] = {}  # symbol → position

    # ------------------------------------------------------------------
    # Open / Close
    # ------------------------------------------------------------------
    def open(self, trade: dict[str, Any]) -> None:
        """Register a new paper position from a trade result dict."""
        symbol = trade["symbol"]
        side = trade.get("side", "Buy")
        entry = trade.get("entry_price", 0.0)
        with self._lock:
            self._positions[symbol] = {
                "symbol": symbol,
                "side": side,
                "size": trade.get("qty", 0.0),
                "entry_price": entry,
                "mark_price": entry,
                "unrealised_pnl": 0.0,
                "leverage": str(trade.get("leverage", 1)),
                "liq_price": None,
                "tp": trade.get("take_profit"),
                "sl": trade.get("stop_loss"),
                "order_id": trade.get("order_id", ""),
            }
        log.info("Paper position opened: %s %s  qty=%.6f  entry=%.4f  TP=%s",
                 side, symbol, trade.get("qty", 0), entry, trade.get("take_profit"))

    def close(self, symbol: str, exit_price: float) -> dict[str, Any] | None:
        """Close a paper position and return result dict with computed P&L.

        Returns ``None`` if no position for *symbol*.
        """
        with self._lock:
            pos = self._positions.pop(symbol, None)
        if pos is None:
            return None

        entry = pos["entry_price"]
        qty = pos["size"]
        if pos["side"] in ("Buy", "LONG"):
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        notional = entry * qty
        pnl_pct = (pnl / notional * 100) if notional > 0 else 0.0

        log.info("Paper position closed: %s %s  entry=%.4f  exit=%.4f  pnl=$%.4f (%.2f%%)",
                 pos["side"], symbol, entry, exit_price, pnl, pnl_pct)
        return {
            **pos,
            "exit_price": exit_price,
            "pnl": round(pnl, 6),
            "pnl_pct": round(pnl_pct, 4),
        }

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_positions(self) -> list[dict[str, Any]]:
        """Return all open paper positions (list of dicts)."""
        with self._lock:
            return [dict(p) for p in self._positions.values()]

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            p = self._positions.get(symbol)
            return dict(p) if p else None

    def has_position(self, symbol: str | None = None) -> bool:
        with self._lock:
            if symbol:
                return symbol in self._positions
            return len(self._positions) > 0

    def count(self) -> int:
        with self._lock:
            return len(self._positions)

    # ------------------------------------------------------------------
    # Mark-price updates
    # ------------------------------------------------------------------
    def update_mark_price(self, symbol: str, mark_price: float) -> None:
        """Update the mark price and recalculate unrealised P&L."""
        with self._lock:
            pos = self._positions.get(symbol)
            if pos is None:
                return
            pos["mark_price"] = mark_price
            entry = pos["entry_price"]
            qty = pos["size"]
            if pos["side"] in ("Buy", "LONG"):
                pos["unrealised_pnl"] = (mark_price - entry) * qty
            else:
                pos["unrealised_pnl"] = (entry - mark_price) * qty

    # ------------------------------------------------------------------
    # TP / SL checks
    # ------------------------------------------------------------------
    def check_tp(self, symbol: str, current_price: float) -> bool:
        """Return *True* if take-profit has been hit for *symbol*."""
        with self._lock:
            pos = self._positions.get(symbol)
            if not pos or not pos.get("tp"):
                return False
            tp = float(pos["tp"])
            if pos["side"] in ("Buy", "LONG"):
                return current_price >= tp
            else:
                return current_price <= tp

    def clear(self) -> None:
        """Remove all paper positions."""
        with self._lock:
            self._positions.clear()
