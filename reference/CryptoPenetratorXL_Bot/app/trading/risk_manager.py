"""
CryptoPenetratorXL — Risk Manager

Full-balance strategy:
  - Trade 100 % of available equity × leverage
  - Only 1 open position at a time
  - No stop loss (hold through drawdowns)
  - Take-profit target: 0.3 – 0.6 % net
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.api.bybit_client import BybitClient
from app.core.config import get_settings
from app.core.constants import Side
from app.core.exceptions import InsufficientBalanceError, RiskLimitExceeded
from app.core.logger import get_logger
from app.strategy.signal_generator import TradeSignal

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.trading.paper_manager import PaperPositionManager

log = get_logger("trading.risk")


@dataclass
class PositionSizing:
    """Computed position sizing for an order."""
    qty: float
    notional: float       # qty × price
    margin_required: float
    leverage: float
    side: Side
    equity: float         # wallet equity at sizing time
    net_tp_pct: float     # expected net TP % after fees


class RiskManager:
    """
    Pre-trade risk checks and position-size calculation.

    Strategy rules:
        1. Maximum 1 open position.
        2. Use 100 % of wallet equity × leverage.
        3. No stop loss (disabled by default).
        4. TP = 0.3 – 0.6 % net (after exchange fees).
    """

    def __init__(self, client: BybitClient) -> None:
        self.client = client
        self._cfg = get_settings()
        self.paper_manager: PaperPositionManager | None = None

    def calculate_position(self, signal: TradeSignal) -> PositionSizing:
        """
        Compute the position size for a given signal.

        Raises RiskLimitExceeded / InsufficientBalanceError on failure.
        """
        cfg = self._cfg
        log.debug("calculate_position  %s %s  entry=%.4f",
                  signal.side, signal.symbol, signal.entry_price)

        # 0. Guard: HOLD → no trade
        if signal.side is None:
            raise RiskLimitExceeded("Signal is HOLD — no trade")

        # 1. Open position limit (always 1 for full-balance strategy)
        if cfg.trading_mode == "paper" and self.paper_manager is not None:
            open_count = self.paper_manager.count()
        else:
            positions = self.client.get_positions()
            open_count = len(positions)
        log.debug("calculate_position  open_positions=%d  max=%d",
                  open_count, cfg.max_open_positions)
        if open_count >= cfg.max_open_positions:
            raise RiskLimitExceeded(
                f"Position already open ({open_count}/{cfg.max_open_positions}). "
                "Close it before opening a new one."
            )

        # 2. Wallet balance
        if cfg.trading_mode == "paper":
            # Paper mode: simulated $10,000 — no API call needed
            equity = 10_000.0
            available = 10_000.0
            log.debug("calculate_position  paper mode — simulated equity=$%.2f", equity)
        else:
            wallet = self.client.get_wallet_balance()
            equity = wallet["equity"]
            available = wallet["available"]
            log.debug("calculate_position  equity=$%.2f  available=$%.2f",
                      equity, available)
            if equity <= 0:
                raise InsufficientBalanceError("Wallet equity is zero")
            # For full-balance strategy with no open positions, equity is the
            # definitive measure.  Some Bybit account types (UNIFIED) may
            # report 'available' as 0 while equity is positive, so we fall
            # back to equity when the position slot check already passed.
            if available <= 0:
                log.info("available=0 but equity=$%.2f — using equity for sizing", equity)
                available = equity

        # 3. Leverage
        leverage = min(signal.leverage, cfg.max_leverage)

        # 4. Position size — full balance
        #    Use min(equity, available) to respect actually available funds, then
        #    apply a 95% safety margin so Bybit has headroom for order-cost
        #    (initial margin + trading fee) without returning ErrCode 110007.
        sizing_balance = min(equity, available)
        if cfg.use_full_balance:
            target_notional = sizing_balance * leverage * 0.95
        else:
            # Fallback: fractional balance (not normally used)
            target_notional = sizing_balance * leverage * 0.90

        # 5. Calculate qty
        price = signal.entry_price
        if price <= 0:
            raise RiskLimitExceeded("Entry price is zero")

        qty = target_notional / price

        # Round to instrument precision
        qty_step = self.client.get_qty_step(signal.symbol)
        min_qty = self.client.get_min_order_qty(signal.symbol)
        qty = self._round_qty(qty, qty_step)
        if qty < min_qty:
            raise InsufficientBalanceError(
                f"Calculated qty {qty} below minimum {min_qty} for {signal.symbol}"
            )

        notional = qty * price
        margin_required = notional / leverage

        # 6. Compute net TP % (after round-trip fees)
        gross_tp = cfg.take_profit_pct
        round_trip_fee = cfg.exchange_fee_pct * 2  # open + close
        net_tp = gross_tp - round_trip_fee

        log.info(
            "Position sized: %s %s  equity=$%.2f  qty=%.6f  notional=$%.2f  "
            "margin=$%.2f  lev=x%.1f  grossTP=%.3f%%  netTP=%.3f%%",
            signal.side.value, signal.symbol, equity, qty, notional,
            margin_required, leverage, gross_tp * 100, net_tp * 100,
        )

        return PositionSizing(
            qty=qty,
            notional=round(notional, 2),
            margin_required=round(margin_required, 2),
            leverage=leverage,
            side=signal.side,
            equity=round(equity, 2),
            net_tp_pct=round(net_tp * 100, 4),
        )

    def compute_take_profit_price(self, signal: TradeSignal) -> float:
        """
        Compute TP price that yields the configured net profit after fees.

        gross_move = take_profit_pct (covers profit + round-trip fees).
        """
        cfg = self._cfg
        price = signal.entry_price
        tp_pct = cfg.take_profit_pct  # already includes margin for fees

        if signal.side == Side.LONG:
            tp = round(price * (1 + tp_pct), 8)
        elif signal.side == Side.SHORT:
            tp = round(price * (1 - tp_pct), 8)
        else:
            tp = 0.0
        log.debug(
            "compute_take_profit_price  %s  entry=%.4f  tp_pct=%.4f  → tp=%.4f",
            signal.side, price, tp_pct, tp,
        )
        return tp

    @staticmethod
    def _round_qty(qty: float, step: float) -> float:
        """Round qty down to the nearest step."""
        if step <= 0:
            return qty
        precision = max(0, -int(math.floor(math.log10(step))))
        return round(math.floor(qty / step) * step, precision)
