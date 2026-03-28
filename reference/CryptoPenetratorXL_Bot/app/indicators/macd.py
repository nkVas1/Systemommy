"""
CryptoPenetratorXL — MACD Indicator (Close, 26, 12, 9)

Your personal setup: fast EMA 12, slow EMA 26, signal EMA 9.
Analyses line crossovers, histogram direction, and divergences.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.logger import get_logger

log = get_logger("indicators.macd")


def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    Add MACD columns.

    Columns added:
        MACD        — MACD line (fast EMA − slow EMA)
        MACD_SIGNAL — signal line (EMA of MACD)
        MACD_HIST   — histogram (MACD − signal)
    """
    df = df.copy()

    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()

    df["MACD"] = ema_fast - ema_slow
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]

    return df


def macd_signal(df: pd.DataFrame) -> dict:
    """
    Analyse the latest MACD state.

    Returns:
        macd, signal, histogram  — current values
        crossover                — 'bullish' | 'bearish' | None
        histogram_direction      — 'expanding' | 'contracting' | 'flat'
        above_zero               — bool (MACD line > 0)
        divergence               — 'bullish' | 'bearish' | None
        score                    — float -1..+1
    """
    if len(df) < 3 or "MACD" not in df.columns:
        return {
            "macd": 0, "signal": 0, "histogram": 0,
            "crossover": None, "histogram_direction": "flat",
            "above_zero": False, "divergence": None, "score": 0.0,
        }

    macd_val = float(df["MACD"].iloc[-1])
    sig_val = float(df["MACD_SIGNAL"].iloc[-1])
    hist = float(df["MACD_HIST"].iloc[-1])
    hist_prev = float(df["MACD_HIST"].iloc[-2])

    macd_prev = float(df["MACD"].iloc[-2])
    sig_prev = float(df["MACD_SIGNAL"].iloc[-2])

    # Crossover
    crossover = None
    if macd_prev <= sig_prev and macd_val > sig_val:
        crossover = "bullish"
    elif macd_prev >= sig_prev and macd_val < sig_val:
        crossover = "bearish"

    # Histogram direction
    if abs(hist) > abs(hist_prev) * 1.02:
        hist_dir = "expanding"
    elif abs(hist) < abs(hist_prev) * 0.98:
        hist_dir = "contracting"
    else:
        hist_dir = "flat"

    above_zero = macd_val > 0

    # Divergence
    divergence = _detect_macd_divergence(df)

    # Score calculation
    score = 0.0

    # Crossover is the strongest signal
    if crossover == "bullish":
        score += 0.45
    elif crossover == "bearish":
        score -= 0.45

    # Histogram momentum
    if hist > 0 and hist_dir == "expanding":
        score += 0.20
    elif hist < 0 and hist_dir == "expanding":
        score -= 0.20
    elif hist > 0 and hist_dir == "contracting":
        score += 0.05
    elif hist < 0 and hist_dir == "contracting":
        score -= 0.05

    # Zero-line position
    if above_zero:
        score += 0.10
    else:
        score -= 0.10

    # Divergence
    if divergence == "bullish":
        score += 0.25
    elif divergence == "bearish":
        score -= 0.25

    score = float(np.clip(score, -1, 1))

    return {
        "macd": round(macd_val, 6),
        "signal": round(sig_val, 6),
        "histogram": round(hist, 6),
        "crossover": crossover,
        "histogram_direction": hist_dir,
        "above_zero": above_zero,
        "divergence": divergence,
        "score": round(score, 3),
    }


def _detect_macd_divergence(df: pd.DataFrame, lookback: int = 30) -> str | None:
    """Detect bullish/bearish divergence between price and MACD histogram."""
    if len(df) < lookback or "MACD_HIST" not in df.columns:
        return None

    window = df.iloc[-lookback:]
    prices = window["close"].values
    hist = window["MACD_HIST"].values

    mid = lookback // 2

    # Bullish: price lower low, histogram higher low
    price_low_1 = np.min(prices[:mid])
    price_low_2 = np.min(prices[mid:])
    hist_low_1 = np.min(hist[:mid])
    hist_low_2 = np.min(hist[mid:])

    if price_low_2 < price_low_1 and hist_low_2 > hist_low_1:
        return "bullish"

    # Bearish: price higher high, histogram lower high
    price_high_1 = np.max(prices[:mid])
    price_high_2 = np.max(prices[mid:])
    hist_high_1 = np.max(hist[:mid])
    hist_high_2 = np.max(hist[mid:])

    if price_high_2 > price_high_1 and hist_high_2 < hist_high_1:
        return "bearish"

    return None
