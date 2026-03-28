"""
CryptoPenetratorXL — CCI (Commodity Channel Index, 20)

Your personal setup: period = 20.
Detects overbought/oversold zones, zero-line crossovers, and divergences.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.constants import CCI_OVERBOUGHT, CCI_OVERSOLD
from app.core.logger import get_logger

log = get_logger("indicators.cci")


def add_cci(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """
    Add CCI column.

    CCI = (Typical Price − SMA of TP) / (0.015 × Mean Deviation)
    """
    df = df.copy()

    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(window=period, min_periods=1).mean()
    mean_dev = tp.rolling(window=period, min_periods=1).apply(
        lambda x: np.mean(np.abs(x - np.mean(x))), raw=True,
    )
    mean_dev = mean_dev.replace(0, np.nan)
    df["CCI"] = (tp - sma_tp) / (0.015 * mean_dev)

    return df


def cci_signal(df: pd.DataFrame) -> dict:
    """
    Analyse the latest CCI state.

    Returns:
        cci             — current value
        zone            — 'oversold' | 'overbought' | 'neutral'
        zero_cross      — 'bullish' | 'bearish' | None
        trend           — 'bullish' | 'bearish' | 'neutral'
        divergence      — 'bullish' | 'bearish' | None
        score           — float -1..+1
    """
    if len(df) < 3 or "CCI" not in df.columns:
        return {"cci": 0, "zone": "neutral", "zero_cross": None, "trend": "neutral", "divergence": None, "score": 0.0}

    cci = float(df["CCI"].iloc[-1])
    cci_prev = float(df["CCI"].iloc[-2])

    # Zone
    if cci < CCI_OVERSOLD:
        zone = "oversold"
    elif cci > CCI_OVERBOUGHT:
        zone = "overbought"
    else:
        zone = "neutral"

    # Zero-line cross
    zero_cross = None
    if cci_prev <= 0 and cci > 0:
        zero_cross = "bullish"
    elif cci_prev >= 0 and cci < 0:
        zero_cross = "bearish"

    # Trend (last 5 bars direction)
    if len(df) >= 5:
        cci_5 = df["CCI"].iloc[-5:].values
        slope = cci_5[-1] - cci_5[0]
        if slope > 10:
            trend = "bullish"
        elif slope < -10:
            trend = "bearish"
        else:
            trend = "neutral"
    else:
        trend = "neutral"

    # Divergence
    divergence = _detect_cci_divergence(df)

    # Score
    score = 0.0

    # Zone
    if zone == "oversold":
        # Reversal potential — bullish
        score += 0.30
    elif zone == "overbought":
        # Reversal potential — bearish
        score -= 0.30

    # Zero cross
    if zero_cross == "bullish":
        score += 0.35
    elif zero_cross == "bearish":
        score -= 0.35

    # Trend momentum
    if trend == "bullish":
        score += 0.15
    elif trend == "bearish":
        score -= 0.15

    # Divergence
    if divergence == "bullish":
        score += 0.20
    elif divergence == "bearish":
        score -= 0.20

    score = float(np.clip(score, -1, 1))

    return {
        "cci": round(cci, 2),
        "zone": zone,
        "zero_cross": zero_cross,
        "trend": trend,
        "divergence": divergence,
        "score": round(score, 3),
    }


def _detect_cci_divergence(df: pd.DataFrame, lookback: int = 20) -> str | None:
    """Detect divergence between price and CCI."""
    if len(df) < lookback or "CCI" not in df.columns:
        return None

    window = df.iloc[-lookback:]
    prices = window["close"].values
    cci_vals = window["CCI"].values
    mid = lookback // 2

    # Bullish: price lower low, CCI higher low
    if np.min(prices[mid:]) < np.min(prices[:mid]) and np.min(cci_vals[mid:]) > np.min(cci_vals[:mid]):
        return "bullish"

    # Bearish: price higher high, CCI lower high
    if np.max(prices[mid:]) > np.max(prices[:mid]) and np.max(cci_vals[mid:]) < np.max(cci_vals[:mid]):
        return "bearish"

    return None
