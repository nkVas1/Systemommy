"""
CryptoPenetratorXL — Indicator Engine

Central orchestrator that applies all four indicators (Volume, Stochastic,
MACD, CCI), computes their individual scores, and produces a unified
confluence analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.core.constants import CONFLUENCE_NORMAL, CONFLUENCE_STRONG, Signal
from app.core.logger import get_logger
from app.indicators.cci import add_cci, cci_signal
from app.indicators.macd import add_macd, macd_signal
from app.indicators.stochastic import add_stochastic, stochastic_signal
from app.indicators.volume import add_volume_indicators, volume_signal

log = get_logger("indicators.engine")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class IndicatorResult:
    """Full analysis result from the indicator engine."""

    symbol: str
    timeframe: str

    # Raw indicator outputs
    volume: dict = field(default_factory=dict)
    stochastic: dict = field(default_factory=dict)
    macd: dict = field(default_factory=dict)
    cci: dict = field(default_factory=dict)

    # Confluence
    confluence_score: float = 0.0   # -1..+1
    signal: Signal = Signal.HOLD
    confidence: float = 0.0         # 0..1

    # Candlestick pattern (optional)
    candle_pattern: str | None = None

    # Current price snapshot
    current_price: float = 0.0
    price_change_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "volume": self.volume,
            "stochastic": self.stochastic,
            "macd": self.macd,
            "cci": self.cci,
            "confluence_score": self.confluence_score,
            "signal": self.signal.value,
            "confidence": self.confidence,
            "candle_pattern": self.candle_pattern,
            "current_price": self.current_price,
            "price_change_pct": self.price_change_pct,
        }


# ---------------------------------------------------------------------------
# Indicator weights (your strategy emphasis)
# ---------------------------------------------------------------------------
WEIGHTS = {
    "volume": 0.15,
    "stochastic": 0.30,
    "macd": 0.30,
    "cci": 0.25,
}

# Confidence multiplier when a signal is suppressed by overbought/oversold zones.
# Reduces confidence to discourage borderline entries against the zone context.
ZONE_SUPPRESSION_CONFIDENCE = 0.5


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class IndicatorEngine:
    """
    Applies Volume + Stochastic(14,1,3) + MACD(12,26,9) + CCI(20)
    and computes a weighted confluence score.
    """

    def __init__(self) -> None:
        cfg = get_settings()
        self.stoch_k = cfg.stoch_k
        self.stoch_d = cfg.stoch_d
        self.stoch_smooth = cfg.stoch_smooth
        self.macd_fast = cfg.macd_fast
        self.macd_slow = cfg.macd_slow
        self.macd_signal = cfg.macd_signal
        self.cci_period = cfg.cci_period

    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add ALL indicator columns to the DataFrame (returns copy)."""
        log.debug("enrich  rows=%d  columns_before=%d", len(df), len(df.columns))
        df = add_volume_indicators(df)
        df = add_stochastic(df, k_period=self.stoch_k, k_slowing=self.stoch_smooth, d_period=self.stoch_d)
        df = add_macd(df, fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
        df = add_cci(df, period=self.cci_period)
        log.debug("enrich  done  columns_after=%d", len(df.columns))
        return df

    def analyse(self, df: pd.DataFrame, symbol: str, timeframe: str) -> IndicatorResult:
        """
        Run full analysis on an enriched DataFrame.

        Returns an IndicatorResult with individual scores and confluence.
        """
        # Ensure indicators are present
        if "STOCH_K" not in df.columns:
            df = self.enrich(df)

        vol = volume_signal(df)
        stoch = stochastic_signal(df)
        macd = macd_signal(df)
        cci = cci_signal(df)

        log.debug(
            "analyse  %s/%s  vol=%.2f  stoch=%.2f  macd=%.2f  cci=%.2f",
            symbol, timeframe, vol["score"], stoch["score"], macd["score"], cci["score"],
        )

        # Weighted confluence
        raw_score = (
            WEIGHTS["volume"] * vol["score"]
            + WEIGHTS["stochastic"] * stoch["score"]
            + WEIGHTS["macd"] * macd["score"]
            + WEIGHTS["cci"] * cci["score"]
        )
        confluence = float(np.clip(raw_score, -1, 1))

        # Determine signal + confidence
        signal, confidence = self._classify(confluence, vol, stoch, macd, cci)

        # Candlestick pattern
        candle = self._detect_candle_pattern(df)
        if candle:
            log.debug("analyse  %s/%s  candle_pattern=%s", symbol, timeframe, candle)

        # Price info
        current_price = float(df["close"].iloc[-1]) if len(df) > 0 else 0.0
        if len(df) >= 2:
            prev_close = float(df["close"].iloc[-2])
            pct = ((current_price - prev_close) / prev_close * 100) if prev_close else 0
        else:
            pct = 0

        result = IndicatorResult(
            symbol=symbol,
            timeframe=timeframe,
            volume=vol,
            stochastic=stoch,
            macd=macd,
            cci=cci,
            confluence_score=round(confluence, 4),
            signal=signal,
            confidence=round(confidence, 3),
            candle_pattern=candle,
            current_price=current_price,
            price_change_pct=round(pct, 3),
        )
        log.info(
            "[%s %s] signal=%s confidence=%.2f confluence=%.3f",
            symbol, timeframe, signal.value, confidence, confluence,
        )
        return result

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------
    @staticmethod
    def _classify(
        confluence: float,
        vol: dict,
        stoch: dict,
        macd: dict,
        cci: dict,
    ) -> tuple[Signal, float]:
        """Map confluence score → Signal enum + confidence 0..1."""
        abs_c = abs(confluence)
        confidence = abs_c  # base confidence = strength of confluence

        # Count how many indicators agree on direction
        scores = [vol["score"], stoch["score"], macd["score"], cci["score"]]
        bullish_count = sum(1 for s in scores if s > 0.05)
        bearish_count = sum(1 for s in scores if s < -0.05)

        # Agreement bonus
        max_agreement = max(bullish_count, bearish_count)
        if max_agreement >= 3:
            confidence = min(confidence + 0.15, 1.0)
        if max_agreement == 4:
            confidence = min(confidence + 0.10, 1.0)

        log.debug(
            "_classify  confluence=%.3f  bullish=%d  bearish=%d  agreement=%d  conf=%.2f",
            confluence, bullish_count, bearish_count, max_agreement, confidence,
        )

        # Zone-based suppression: prevent buying in overbought or selling in
        # oversold conditions.  When both Stochastic and CCI agree the market
        # is extended, downgrade the signal to HOLD to avoid false entries.
        stoch_zone = stoch.get("zone", "neutral")
        cci_zone = cci.get("zone", "neutral")

        if confluence > 0:  # bullish signal candidate
            overbought_count = sum(1 for z in (stoch_zone, cci_zone) if z == "overbought")
            if overbought_count >= 2:
                log.info(
                    "_classify  suppressed BUY — overbought in %d zone(s) "
                    "(stoch=%s, cci=%s, confluence=%.3f)",
                    overbought_count, stoch_zone, cci_zone, confluence,
                )
                return Signal.HOLD, confidence * ZONE_SUPPRESSION_CONFIDENCE
        elif confluence < 0:  # bearish signal candidate
            oversold_count = sum(1 for z in (stoch_zone, cci_zone) if z == "oversold")
            if oversold_count >= 2:
                log.info(
                    "_classify  suppressed SELL — oversold in %d zone(s) "
                    "(stoch=%s, cci=%s, confluence=%.3f)",
                    oversold_count, stoch_zone, cci_zone, confluence,
                )
                return Signal.HOLD, confidence * ZONE_SUPPRESSION_CONFIDENCE

        # If 3+ indicators agree in direction, promote to at least a NORMAL signal
        # even if the weighted average is below the threshold (common for scalping).
        # Only apply when zones are neutral (not overbought/oversold).
        if max_agreement >= 3 and abs_c < CONFLUENCE_NORMAL and abs_c > 0.05:
            if confluence > 0 and stoch_zone != "overbought":
                return Signal.BUY, max(confidence, 0.35)
            elif confluence < 0 and stoch_zone != "oversold":
                return Signal.SELL, max(confidence, 0.35)

        # Standard classification
        if confluence >= CONFLUENCE_STRONG:
            return Signal.STRONG_BUY, confidence
        elif confluence >= CONFLUENCE_NORMAL:
            return Signal.BUY, confidence
        elif confluence <= -CONFLUENCE_STRONG:
            return Signal.STRONG_SELL, confidence
        elif confluence <= -CONFLUENCE_NORMAL:
            return Signal.SELL, confidence
        else:
            return Signal.HOLD, confidence

    # ------------------------------------------------------------------
    # Candlestick patterns
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_candle_pattern(df: pd.DataFrame) -> str | None:
        """Detect basic candlestick patterns on the last few bars."""
        if len(df) < 3:
            return None

        c = df.iloc[-1]
        p = df.iloc[-2]
        pp = df.iloc[-3]

        body = c["close"] - c["open"]
        body_abs = abs(body)
        upper_wick = c["high"] - max(c["close"], c["open"])
        lower_wick = min(c["close"], c["open"]) - c["low"]
        total_range = c["high"] - c["low"]
        if total_range == 0:
            return None

        p_body = p["close"] - p["open"]

        # Hammer / Inverted Hammer
        if lower_wick > body_abs * 2 and upper_wick < body_abs * 0.5:
            return "Hammer" if body >= 0 else "Hanging Man"

        if upper_wick > body_abs * 2 and lower_wick < body_abs * 0.5:
            return "Inverted Hammer" if body >= 0 else "Shooting Star"

        # Doji
        if body_abs < total_range * 0.1:
            return "Doji"

        # Engulfing
        if body > 0 and p_body < 0 and c["close"] > p["open"] and c["open"] < p["close"]:
            return "Bullish Engulfing"
        if body < 0 and p_body > 0 and c["close"] < p["open"] and c["open"] > p["close"]:
            return "Bearish Engulfing"

        # Morning/Evening Star (3-candle)
        pp_body = pp["close"] - pp["open"]
        p_body_abs = abs(p_body)
        if pp_body < 0 and p_body_abs < abs(pp_body) * 0.3 and body > 0 and c["close"] > (pp["open"] + pp["close"]) / 2:
            return "Morning Star"
        if pp_body > 0 and p_body_abs < abs(pp_body) * 0.3 and body < 0 and c["close"] < (pp["open"] + pp["close"]) / 2:
            return "Evening Star"

        return None
