"""
CryptoPenetratorXL — Stochastic Oscillator (14, 1, 3)

Your personal setup: %K period 14, %K slowing 1, %D period 3.
Detects oversold / overbought zones and %K/%D crossovers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.constants import STOCH_OVERBOUGHT, STOCH_OVERSOLD
from app.core.logger import get_logger

log = get_logger("indicators.stochastic")


def add_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    k_slowing: int = 1,
    d_period: int = 3,
) -> pd.DataFrame:
    """
    Add Stochastic Oscillator columns.

    Columns added:
        STOCH_K    — %K line (fast stochastic, slowed by k_slowing)
        STOCH_D    — %D line (SMA of %K with d_period)
    """
    df = df.copy()

    low_min = df["low"].rolling(window=k_period, min_periods=1).min()
    high_max = df["high"].rolling(window=k_period, min_periods=1).max()

    raw_k = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)

    # Apply slowing
    if k_slowing > 1:
        df["STOCH_K"] = raw_k.rolling(window=k_slowing, min_periods=1).mean()
    else:
        df["STOCH_K"] = raw_k

    df["STOCH_D"] = df["STOCH_K"].rolling(window=d_period, min_periods=1).mean()

    return df


def stochastic_signal(df: pd.DataFrame) -> dict:
    """
    Analyse the latest stochastic state.

    Returns dict with keys:
        k, d              — current values
        zone              — 'oversold' | 'overbought' | 'neutral'
        crossover         — 'bullish' | 'bearish' | None
        divergence        — 'bullish' | 'bearish' | None
        score             — float -1..+1
    """
    if len(df) < 3 or "STOCH_K" not in df.columns:
        return {"k": 50, "d": 50, "zone": "neutral", "crossover": None, "divergence": None, "score": 0.0}

    k = float(df["STOCH_K"].iloc[-1])
    d = float(df["STOCH_D"].iloc[-1])
    k_prev = float(df["STOCH_K"].iloc[-2])
    d_prev = float(df["STOCH_D"].iloc[-2])

    # Zone
    if k < STOCH_OVERSOLD:
        zone = "oversold"
    elif k > STOCH_OVERBOUGHT:
        zone = "overbought"
    else:
        zone = "neutral"

    # Crossover
    crossover = None
    if k_prev <= d_prev and k > d:
        crossover = "bullish"
    elif k_prev >= d_prev and k < d:
        crossover = "bearish"

    # Simple divergence detection (price making new low but stoch not)
    divergence = _detect_divergence(df)

    # Score
    score = 0.0
    # Zone contribution
    if zone == "oversold":
        score += 0.35
    elif zone == "overbought":
        score -= 0.35

    # Crossover contribution
    if crossover == "bullish":
        score += 0.40
    elif crossover == "bearish":
        score -= 0.40

    # Divergence contribution
    if divergence == "bullish":
        score += 0.25
    elif divergence == "bearish":
        score -= 0.25

    score = float(np.clip(score, -1, 1))

    return {
        "k": round(k, 2),
        "d": round(d, 2),
        "zone": zone,
        "crossover": crossover,
        "divergence": divergence,
        "score": round(score, 3),
    }


def _detect_divergence(df: pd.DataFrame, lookback: int = 20) -> str | None:
    """Detect bullish/bearish divergence between price and stochastic."""
    if len(df) < lookback:
        return None

    window = df.iloc[-lookback:]
    prices = window["close"].values
    stoch = window["STOCH_K"].values

    # Find local lows
    price_min_idx = np.argmin(prices[-10:])
    stoch_at_price_min = stoch[-10:][price_min_idx]

    # Bullish divergence: price makes lower low, stoch makes higher low
    if price_min_idx > 0:
        prev_price_min = np.min(prices[-lookback:-10]) if lookback > 10 else prices[0]
        prev_stoch_min = np.min(stoch[-lookback:-10]) if lookback > 10 else stoch[0]
        if prices[-10:][price_min_idx] < prev_price_min and stoch_at_price_min > prev_stoch_min:
            return "bullish"

    # Find local highs
    price_max_idx = np.argmax(prices[-10:])
    stoch_at_price_max = stoch[-10:][price_max_idx]

    if price_max_idx > 0:
        prev_price_max = np.max(prices[-lookback:-10]) if lookback > 10 else prices[0]
        prev_stoch_max = np.max(stoch[-lookback:-10]) if lookback > 10 else stoch[0]
        if prices[-10:][price_max_idx] > prev_price_max and stoch_at_price_max < prev_stoch_max:
            return "bearish"

    return None
