"""
CryptoPenetratorXL — Volume Indicator Analysis

Analyses raw volume bars, volume moving average, volume ratio,
On-Balance Volume (OBV), and detects volume spikes / divergences.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.constants import VOLUME_SPIKE_MULT
from app.core.logger import get_logger

log = get_logger("indicators.volume")


def add_volume_indicators(df: pd.DataFrame, ma_period: int = 20) -> pd.DataFrame:
    """
    Add volume-based columns to *df* (in-place + returns df).

    Columns added:
        VOL_MA       — simple moving average of volume
        VOL_RATIO    — current volume / VOL_MA
        OBV          — On-Balance Volume
        VOL_DELTA    — buy volume − sell volume (estimated via close vs open)
        VOL_SPIKE    — boolean, True when VOL_RATIO >= spike multiplier
    """
    df = df.copy()

    # Volume MA & ratio
    df["VOL_MA"] = df["volume"].rolling(window=ma_period, min_periods=1).mean()
    df["VOL_RATIO"] = df["volume"] / df["VOL_MA"].replace(0, np.nan)

    # OBV
    direction = np.where(df["close"] >= df["close"].shift(1), 1, -1)
    direction[0] = 0
    df["OBV"] = (df["volume"] * direction).cumsum()

    # Buy/sell volume estimate (close vs open proportion of range)
    total_range = df["high"] - df["low"]
    total_range = total_range.replace(0, np.nan)
    buy_pct = (df["close"] - df["low"]) / total_range
    df["VOL_DELTA"] = df["volume"] * (2 * buy_pct - 1)

    # Spike flag
    df["VOL_SPIKE"] = df["VOL_RATIO"] >= VOLUME_SPIKE_MULT

    return df


def volume_signal(df: pd.DataFrame) -> dict:
    """
    Return a dict summarising the latest volume analysis.

    Keys: vol_ratio, obv_trend, vol_spike, vol_delta_sum, score (-1..+1).
    """
    if len(df) < 5:
        return {"vol_ratio": 0, "obv_trend": 0, "vol_spike": False, "vol_delta_sum": 0, "score": 0.0}

    last = df.iloc[-1]
    prev5 = df.iloc[-5:]

    vol_ratio = float(last.get("VOL_RATIO", 1.0))
    vol_spike = bool(last.get("VOL_SPIKE", False))

    # OBV trend: slope of last 10 bars
    obv_window = df["OBV"].iloc[-10:]
    if len(obv_window) >= 2:
        obv_slope = (obv_window.iloc[-1] - obv_window.iloc[0]) / max(len(obv_window), 1)
    else:
        obv_slope = 0

    obv_trend = 1 if obv_slope > 0 else (-1 if obv_slope < 0 else 0)

    # Cumulative delta (last 5 bars)
    vol_delta_sum = float(prev5["VOL_DELTA"].sum()) if "VOL_DELTA" in prev5.columns else 0.0

    # Composite score
    score = 0.0
    if vol_spike:
        score += 0.3 * (1 if vol_delta_sum > 0 else -1)
    score += 0.4 * obv_trend
    score += 0.3 * np.clip(vol_delta_sum / (abs(vol_delta_sum) + 1e-9), -1, 1)
    score = float(np.clip(score, -1, 1))

    return {
        "vol_ratio": round(vol_ratio, 2),
        "obv_trend": obv_trend,
        "vol_spike": vol_spike,
        "vol_delta_sum": round(vol_delta_sum, 2),
        "score": round(score, 3),
    }
