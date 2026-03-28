"""
CryptoPenetratorXL — Signal Generator  v2.1

Pulls kline data, runs the Indicator Engine, and produces actionable
trade signals.  Full-balance strategy: no SL, TP-only (0.3-0.6 % net).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.api.bybit_client import BybitClient
from app.core.config import get_settings
from app.core.constants import Signal, Side
from app.core.logger import get_logger
from app.indicators.engine import IndicatorEngine, IndicatorResult

log = get_logger("strategy.signal")


@dataclass
class TradeSignal:
    """A concrete, actionable trade recommendation."""

    symbol: str
    signal: Signal
    side: Side | None         # None when HOLD
    confidence: float         # 0..1
    entry_price: float
    stop_loss: float          # 0 when SL disabled
    take_profit: float
    leverage: float
    timeframe: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    indicator_detail: dict = field(default_factory=dict)
    candle_pattern: str | None = None
    notes: str = ""

    @property
    def risk_reward_ratio(self) -> float:
        """R:R ratio.  Returns 0 when SL is disabled (stop_loss == 0)."""
        if self.side is None or self.entry_price == 0 or self.stop_loss == 0:
            return 0.0
        reward = abs(self.take_profit - self.entry_price)
        risk = abs(self.entry_price - self.stop_loss)
        return round(reward / risk, 2) if risk > 0 else 0.0

    @property
    def tp_pct(self) -> float:
        """Gross TP distance in % from entry."""
        if self.entry_price == 0 or self.take_profit == 0 or self.side is None:
            return 0.0
        return round(abs(self.take_profit - self.entry_price) / self.entry_price * 100, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "signal": self.signal.value,
            "side": self.side.value if self.side else None,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "leverage": self.leverage,
            "tp_pct": self.tp_pct,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat(),
            "candle_pattern": self.candle_pattern,
            "notes": self.notes,
        }


class SignalGenerator:
    """
    Orchestrates data fetching → indicator analysis → signal production.
    """

    def __init__(self, client: BybitClient) -> None:
        self.client = client
        self.engine = IndicatorEngine()
        self._cfg = get_settings()

    def generate(
        self,
        symbol: str,
        timeframe: str = "15",
        candles: int = 200,
    ) -> TradeSignal:
        """
        Fetch klines, run indicator analysis, produce a trade signal.
        """
        log.debug("generate  symbol=%s  tf=%s  candles=%d", symbol, timeframe, candles)
        # 1. Fetch data
        df = self.client.get_klines(symbol, interval=timeframe, limit=candles)
        if df.empty or len(df) < 30:
            log.warning("Insufficient data for %s (%d rows)", symbol, len(df))
            return self._hold_signal(symbol, timeframe)

        # 2. Enrich & analyse
        df = self.engine.enrich(df)
        result: IndicatorResult = self.engine.analyse(df, symbol, timeframe)

        # 3. Build trade signal
        sig = self._build_signal(result, df)
        log.info(
            "generate  %s/%s → %s  conf=%.2f  entry=%.4f",
            symbol, timeframe, sig.signal.value, sig.confidence, sig.entry_price,
        )
        return sig

    def generate_from_df(
        self,
        df: "pd.DataFrame",
        symbol: str,
        timeframe: str = "15",
    ) -> TradeSignal:
        """
        Produce a trade signal from an already-fetched & enriched DataFrame.

        Use this to avoid a redundant ``get_klines`` round-trip when the
        caller already has the data (e.g. ``AnalysisWorker``).
        """
        log.debug("generate_from_df  symbol=%s  tf=%s  rows=%d",
                  symbol, timeframe, len(df) if df is not None else 0)
        if df is None or df.empty or len(df) < 30:
            return self._hold_signal(symbol, timeframe)

        result: IndicatorResult = self.engine.analyse(df, symbol, timeframe)
        return self._build_signal(result, df)

    def generate_multi_timeframe(
        self,
        symbol: str,
        timeframes: list[str] | None = None,
    ) -> TradeSignal:
        """
        Multi-timeframe analysis: analyse several timeframes, produce
        a consolidated signal with the highest-confidence alignment.
        """
        if timeframes is None:
            timeframes = ["5", "15", "60"]
        log.info("generate_multi_timeframe  symbol=%s  tfs=%s", symbol, timeframes)

        results: list[IndicatorResult] = []
        dfs: dict[str, Any] = {}
        for tf in timeframes:
            try:
                df = self.client.get_klines(symbol, interval=tf, limit=200)
                if len(df) < 30:
                    continue
                df = self.engine.enrich(df)
                r = self.engine.analyse(df, symbol, tf)
                results.append(r)
                dfs[tf] = df
            except Exception as e:
                log.warning("MTF analysis failed for %s/%s: %s", symbol, tf, e)

        if not results:
            return self._hold_signal(symbol, "MTF")

        # Weighted average (higher timeframes carry more weight)
        tf_weights = {"1": 0.5, "3": 0.6, "5": 0.7, "15": 1.0, "30": 1.1, "60": 1.2, "240": 1.3, "D": 1.5}
        total_w = 0
        weighted_score = 0.0
        best_result = results[0]
        best_confidence = 0.0

        for r in results:
            w = tf_weights.get(r.timeframe, 1.0)
            weighted_score += r.confluence_score * w
            total_w += w
            if r.confidence > best_confidence:
                best_confidence = r.confidence
                best_result = r

        if total_w > 0:
            avg_score = weighted_score / total_w
        else:
            avg_score = 0

        log.debug(
            "MTF weighted_score=%.4f  total_w=%.2f  avg=%.4f  best_tf=%s",
            weighted_score, total_w, avg_score, best_result.timeframe,
        )

        # Override the best result's confluence with the MTF weighted score
        best_result.confluence_score = round(avg_score, 4)
        best_result.timeframe = "MTF"

        # Use the primary (15m) dataframe for TP calc if available
        primary_tf = "15" if "15" in dfs else timeframes[0]
        df = dfs.get(primary_tf, list(dfs.values())[0] if dfs else None)
        if df is None:
            return self._hold_signal(symbol, "MTF")

        return self._build_signal(best_result, df)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_signal(self, result: IndicatorResult, df: Any) -> TradeSignal:
        """
        Convert an IndicatorResult into a TradeSignal.

        Strategy:
          • SL = 0 (disabled) when `use_stop_loss` is False
          • TP = entry × (1 ± take_profit_pct)   [gross target]
          • Net profit is computed later by RiskManager (subtracts fees)
        """
        cfg = self._cfg
        price = result.current_price

        if result.signal in (Signal.STRONG_BUY, Signal.BUY):
            side = Side.LONG
            tp = price * (1 + cfg.take_profit_pct)
            sl = price * (1 - cfg.stop_loss_pct) if cfg.use_stop_loss else 0.0
        elif result.signal in (Signal.STRONG_SELL, Signal.SELL):
            side = Side.SHORT
            tp = price * (1 - cfg.take_profit_pct)
            sl = price * (1 + cfg.stop_loss_pct) if cfg.use_stop_loss else 0.0
        else:
            side = None
            sl = 0.0
            tp = 0.0

        # Optional: ATR-dynamic SL (only when SL is enabled)
        if cfg.use_stop_loss and "ATR" in df.columns and len(df) > 0 and side is not None:
            atr = float(df["ATR"].iloc[-1]) if not df["ATR"].isna().iloc[-1] else 0
            if atr > 0:
                if side == Side.LONG:
                    sl = max(sl, price - 2.0 * atr)
                else:
                    sl = min(sl, price + 2.0 * atr)

        leverage = cfg.default_leverage

        notes_parts = []
        if result.candle_pattern:
            notes_parts.append(f"Candle: {result.candle_pattern}")
        if result.volume.get("vol_spike"):
            notes_parts.append("Volume spike detected")
        if not cfg.use_stop_loss:
            notes_parts.append("SL disabled — hold through drawdown")

        log.debug(
            "_build_signal  %s  signal=%s  side=%s  price=%.4f  sl=%.4f  tp=%.4f  lev=x%.1f",
            result.symbol, result.signal.value, side, price, sl, tp, leverage,
        )

        return TradeSignal(
            symbol=result.symbol,
            signal=result.signal,
            side=side,
            confidence=result.confidence,
            entry_price=price,
            stop_loss=round(sl, 8),
            take_profit=round(tp, 8),
            leverage=leverage,
            timeframe=result.timeframe,
            indicator_detail=result.to_dict(),
            candle_pattern=result.candle_pattern,
            notes="; ".join(notes_parts),
        )

    @staticmethod
    def _hold_signal(symbol: str, timeframe: str) -> TradeSignal:
        return TradeSignal(
            symbol=symbol,
            signal=Signal.HOLD,
            side=None,
            confidence=0.0,
            entry_price=0,
            stop_loss=0,
            take_profit=0,
            leverage=1,
            timeframe=timeframe,
            notes="Insufficient data or no clear signal",
        )
