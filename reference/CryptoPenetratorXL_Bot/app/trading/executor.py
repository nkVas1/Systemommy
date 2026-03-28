"""
CryptoPenetratorXL — Trade Executor

Bridges signal generation → risk management → Bybit order placement.
Full-balance strategy: no SL, TP-only, single position.
Supports paper-trading mode for safe testing.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from app.api.bybit_client import BybitClient
from app.core.config import get_settings
from app.core.constants import OrderType, Signal, Side
from app.core.exceptions import OrderExecutionError
from app.core.logger import get_logger
from app.strategy.signal_generator import TradeSignal
from app.trading.risk_manager import PositionSizing, RiskManager

log = get_logger("trading.executor")


class TradeExecutor:
    """
    Executes trade signals after risk validation.

    Supports two modes:
        - paper: logs trades but does NOT send orders to exchange
        - live:  sends real orders to Bybit (limit orders with small offset)
    """

    # Small price offset for limit orders — ensures near-instant fill while
    # qualifying for maker fees instead of higher taker fees.
    LIMIT_OFFSET_PCT = 0.0001  # 0.01%

    def __init__(self, client: BybitClient) -> None:
        self.client = client
        self.risk = RiskManager(client)
        self._cfg = get_settings()
        self._trade_log: list[dict[str, Any]] = []

    @property
    def is_live(self) -> bool:
        return self._cfg.trading_mode == "live"

    def execute(self, signal: TradeSignal) -> dict[str, Any]:
        """
        Validate risk, set leverage, place order (or paper-trade).

        Returns a dict with trade details.
        """
        log.info(
            "execute  %s %s  signal=%s  conf=%.2f  entry=%.4f",
            signal.side, signal.symbol, signal.signal.value,
            signal.confidence, signal.entry_price,
        )
        if signal.signal == Signal.HOLD or signal.side is None:
            log.info("Signal is HOLD — skipping execution for %s", signal.symbol)
            return {"status": "skipped", "reason": "HOLD signal"}

        # 1. Risk check + sizing (full-balance)
        try:
            sizing: PositionSizing = self.risk.calculate_position(signal)
        except Exception as e:
            log.warning("Risk check failed: %s", e)
            return {"status": "rejected", "reason": str(e)}

        # 2. Compute TP price
        tp_price = self.risk.compute_take_profit_price(signal)

        # 3. SL — only if explicitly enabled
        sl_price = signal.stop_loss if self._cfg.use_stop_loss and signal.stop_loss > 0 else None

        # 4. Set leverage
        try:
            self.client.set_leverage(signal.symbol, sizing.leverage)
        except Exception as e:
            log.warning("set_leverage error (continuing): %s", e)

        # 4b. Cancel stale pending limit orders to free locked margin.
        #     Position-level TP/SL (set via takeProfit/stopLoss params) are NOT
        #     affected by cancel_all_orders — they are part of the position.
        if self.is_live:
            try:
                self.client.cancel_all_orders(signal.symbol)
            except Exception as e:
                log.debug("cancel_all_orders before new order: %s", e)

        # 5. Place order
        if self.is_live:
            result = self._place_live_order(signal, sizing, tp_price, sl_price)
        else:
            result = self._place_paper_order(signal, sizing, tp_price, sl_price)

        self._trade_log.append(result)
        return result

    def close_position(self, symbol: str, side: Side, qty: float) -> dict[str, Any]:
        """Close an open position."""
        if self.is_live:
            try:
                resp = self.client.close_position(symbol, side, qty)
                log.info("Position closed: %s %s qty=%s", side.value, symbol, qty)
                return {"status": "closed", "symbol": symbol, "detail": resp}
            except Exception as e:
                log.error("Close position failed: %s", e)
                return {"status": "error", "reason": str(e)}
        else:
            log.info("[PAPER] Position closed: %s %s qty=%s", side.value, symbol, qty)
            return {"status": "paper_closed", "symbol": symbol}

    @property
    def trade_history(self) -> list[dict[str, Any]]:
        return list(self._trade_log)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------
    def _place_live_order(
        self,
        signal: TradeSignal,
        sizing: PositionSizing,
        tp_price: float,
        sl_price: float | None,
    ) -> dict[str, Any]:
        """Send a real limit order to Bybit with a small offset from market price.

        Using limit orders instead of market orders reduces taker fees.
        The offset is small enough (0.01%) to ensure near-instant fill.
        """
        try:
            # Small offset from current price for near-instant limit fill
            offset_pct = self.LIMIT_OFFSET_PCT
            entry = signal.entry_price
            if signal.side == Side.LONG:
                limit_price = entry * (1 + offset_pct)   # slightly above for buy
            else:
                limit_price = entry * (1 - offset_pct)   # slightly below for sell

            # Round to tick size
            limit_price = self._round_price(signal.symbol, limit_price)

            resp = self.client.place_order(
                symbol=signal.symbol,
                side=signal.side,
                qty=sizing.qty,
                order_type=OrderType.LIMIT,
                price=limit_price,
                sl=sl_price,
                tp=tp_price if tp_price > 0 else None,
            )
            log.info(
                "LIVE LIMIT order placed: %s %s qty=%.6f limit=%.4f (market≈%.4f) "
                "TP=%.4f SL=%s equity=$%.2f",
                signal.side.value, signal.symbol, sizing.qty,
                limit_price, entry, tp_price,
                f"{sl_price:.4f}" if sl_price else "NONE",
                sizing.equity,
            )
            return {
                "status": "filled",
                "mode": "live",
                "order_id": resp.get("orderId", ""),
                "symbol": signal.symbol,
                "side": signal.side.value,
                "qty": sizing.qty,
                "entry_price": limit_price,
                "stop_loss": sl_price or 0,
                "take_profit": tp_price,
                "leverage": sizing.leverage,
                "confidence": signal.confidence,
                "equity": sizing.equity,
                "notional": sizing.notional,
                "net_tp_pct": sizing.net_tp_pct,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            log.error("LIVE order failed: %s", e)
            raise OrderExecutionError(str(e)) from e

    def _place_paper_order(
        self,
        signal: TradeSignal,
        sizing: PositionSizing,
        tp_price: float,
        sl_price: float | None,
    ) -> dict[str, Any]:
        """Simulate a trade without sending to the exchange."""
        trade_id = f"paper_{uuid.uuid4().hex[:8]}"
        log.info(
            "PAPER order: %s %s qty=%.6f price=%.4f TP=%.4f SL=%s equity=$%.2f [id=%s]",
            signal.side.value, signal.symbol, sizing.qty,
            signal.entry_price, tp_price,
            f"{sl_price:.4f}" if sl_price else "NONE",
            sizing.equity, trade_id,
        )
        return {
            "status": "paper_filled",
            "mode": "paper",
            "order_id": trade_id,
            "symbol": signal.symbol,
            "side": signal.side.value,
            "qty": sizing.qty,
            "entry_price": signal.entry_price,
            "stop_loss": sl_price or 0,
            "take_profit": tp_price,
            "leverage": sizing.leverage,
            "confidence": signal.confidence,
            "equity": sizing.equity,
            "notional": sizing.notional,
            "net_tp_pct": sizing.net_tp_pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _round_price(self, symbol: str, price: float) -> float:
        """Round price to the instrument tick size."""
        tick = self.client.get_tick_size(symbol)
        if tick <= 0:
            return round(price, 2)
        precision = max(0, -int(math.floor(math.log10(tick))))
        return round(round(price / tick) * tick, precision)
