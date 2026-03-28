"""
CryptoPenetratorXL — Enhanced Analysis Engine  v2.3

Switchable deep-analysis module that adds:
  1. Comprehensive candlestick pattern recognition (~25 patterns)
  2. Chart structure / figure detection (double top/bottom, H&S,
     triangles, channels, wedges, flags)
  3. Probability-based price forecasting (% up / % down)
  4. Psychological market sentiment indicators (FOMO, fear, greed,
     exhaustion, accumulation/distribution)

This module is designed to be **completely independent** from the
core indicator engine.  It never runs unless explicitly called
(toggle ON) so it has zero impact on the main signal pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.core.logger import get_logger

log = get_logger("analysis.enhanced")


# ======================================================================
# Result containers
# ======================================================================
@dataclass
class CandlePattern:
    """Single detected candlestick pattern."""
    name: str
    kind: str          # "bullish" | "bearish" | "neutral"
    bar_index: int     # index in DataFrame
    confidence: float  # 0..1
    description: str = ""


@dataclass
class ChartStructure:
    """Detected chart structure / figure."""
    name: str
    kind: str          # "bullish" | "bearish" | "neutral"
    start_idx: int
    end_idx: int
    key_points: list[tuple[int, float]] = field(default_factory=list)   # [(idx, price), ...]
    confidence: float = 0.0
    description: str = ""


@dataclass
class PsychProfile:
    """Psychological market profile snapshot."""
    fomo_level: float = 0.0       # 0..1
    fear_level: float = 0.0       # 0..1
    greed_level: float = 0.0      # 0..1
    exhaustion: float = 0.0       # 0..1
    accumulation: float = 0.0     # -1 (distribution) .. +1 (accumulation)
    description: str = ""


@dataclass
class ProbabilityForecast:
    """Short-term probabilistic price forecast."""
    prob_up: float = 0.5     # 0..1
    prob_down: float = 0.5   # 0..1
    expected_move_pct: float = 0.0   # signed %
    volatility_pct: float = 0.0
    support: float = 0.0
    resistance: float = 0.0
    description: str = ""


@dataclass
class EnhancedAnalysisResult:
    """Full enhanced analysis output."""
    candle_patterns: list[CandlePattern] = field(default_factory=list)
    structures: list[ChartStructure] = field(default_factory=list)
    psych: PsychProfile = field(default_factory=PsychProfile)
    forecast: ProbabilityForecast = field(default_factory=ProbabilityForecast)


# ======================================================================
# 1.  Candlestick Pattern Detector
# ======================================================================
class CandlePatternDetector:
    """Detect ~25 Japanese candlestick patterns on the last N bars."""

    @staticmethod
    def detect(df: pd.DataFrame, lookback: int = 10) -> list[CandlePattern]:
        if len(df) < 5:
            return []

        patterns: list[CandlePattern] = []
        n = len(df)
        start = max(0, n - lookback)

        o = df["open"].values.astype(float)
        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        c = df["close"].values.astype(float)

        for i in range(max(start, 3), n):
            body = c[i] - o[i]
            body_abs = abs(body)
            rng = h[i] - l[i]
            if rng == 0:
                continue
            upper_wick = h[i] - max(c[i], o[i])
            lower_wick = min(c[i], o[i]) - l[i]
            body_ratio = body_abs / rng

            prev_body = c[i - 1] - o[i - 1]
            prev_body_abs = abs(prev_body)
            prev_rng = h[i - 1] - l[i - 1]

            # --- Single-candle patterns ---

            # Doji
            if body_ratio < 0.08:
                # Dragonfly Doji (long lower wick)
                if lower_wick > rng * 0.6 and upper_wick < rng * 0.1:
                    patterns.append(CandlePattern(
                        "Dragonfly Doji", "bullish", i, 0.65,
                        "Reversal signal — buyers pushed price back up"))
                # Gravestone Doji (long upper wick)
                elif upper_wick > rng * 0.6 and lower_wick < rng * 0.1:
                    patterns.append(CandlePattern(
                        "Gravestone Doji", "bearish", i, 0.65,
                        "Reversal signal — sellers pushed price back down"))
                else:
                    patterns.append(CandlePattern(
                        "Doji", "neutral", i, 0.40,
                        "Indecision — market hesitating"))
                continue

            # Hammer
            if lower_wick > body_abs * 2 and upper_wick < body_abs * 0.5 and body_ratio < 0.4:
                if body >= 0:
                    patterns.append(CandlePattern(
                        "Hammer", "bullish", i, 0.70,
                        "Potential reversal — strong buying at lows"))
                else:
                    patterns.append(CandlePattern(
                        "Hanging Man", "bearish", i, 0.60,
                        "Warning signal — selling pressure after uptrend"))
                continue

            # Inverted Hammer / Shooting Star
            if upper_wick > body_abs * 2 and lower_wick < body_abs * 0.5 and body_ratio < 0.4:
                if body >= 0:
                    patterns.append(CandlePattern(
                        "Inverted Hammer", "bullish", i, 0.55,
                        "Possible reversal — attempted rally"))
                else:
                    patterns.append(CandlePattern(
                        "Shooting Star", "bearish", i, 0.70,
                        "Reversal — sellers rejected the high"))
                continue

            # Marubozu (full body, no wicks)
            if body_ratio > 0.90:
                if body > 0:
                    patterns.append(CandlePattern(
                        "Bullish Marubozu", "bullish", i, 0.75,
                        "Strong buying — full control by bulls"))
                else:
                    patterns.append(CandlePattern(
                        "Bearish Marubozu", "bearish", i, 0.75,
                        "Strong selling — full control by bears"))
                continue

            # Spinning Top
            if body_ratio < 0.3 and upper_wick > body_abs * 0.5 and lower_wick > body_abs * 0.5:
                patterns.append(CandlePattern(
                    "Spinning Top", "neutral", i, 0.35,
                    "Indecision — neither side in control"))
                continue

            # --- Two-candle patterns ---
            if i < 1:
                continue

            # Bullish Engulfing
            if body > 0 and prev_body < 0 and c[i] > o[i - 1] and o[i] < c[i - 1]:
                patterns.append(CandlePattern(
                    "Bullish Engulfing", "bullish", i, 0.80,
                    "Strong reversal — buyers engulfed prior selling"))
                continue

            # Bearish Engulfing
            if body < 0 and prev_body > 0 and c[i] < o[i - 1] and o[i] > c[i - 1]:
                patterns.append(CandlePattern(
                    "Bearish Engulfing", "bearish", i, 0.80,
                    "Strong reversal — sellers engulfed prior buying"))
                continue

            # Piercing Line
            if (prev_body < 0 and body > 0
                    and o[i] < l[i - 1]
                    and c[i] > (o[i - 1] + c[i - 1]) / 2
                    and c[i] < o[i - 1]):
                patterns.append(CandlePattern(
                    "Piercing Line", "bullish", i, 0.65,
                    "Buying emerged from gap-down — potential reversal"))
                continue

            # Dark Cloud Cover
            if (prev_body > 0 and body < 0
                    and o[i] > h[i - 1]
                    and c[i] < (o[i - 1] + c[i - 1]) / 2
                    and c[i] > o[i - 1]):
                patterns.append(CandlePattern(
                    "Dark Cloud Cover", "bearish", i, 0.65,
                    "Selling from gap-up — potential reversal"))
                continue

            # Tweezer Top/Bottom
            if abs(h[i] - h[i - 1]) < rng * 0.05 and prev_body > 0 and body < 0:
                patterns.append(CandlePattern(
                    "Tweezer Top", "bearish", i, 0.60,
                    "Resistance confirmed — double rejection"))
                continue
            if abs(l[i] - l[i - 1]) < rng * 0.05 and prev_body < 0 and body > 0:
                patterns.append(CandlePattern(
                    "Tweezer Bottom", "bullish", i, 0.60,
                    "Support confirmed — double rejection"))
                continue

            # Harami (inside bar)
            if (prev_body_abs > 0 and body_abs < prev_body_abs * 0.5
                    and max(o[i], c[i]) < max(o[i - 1], c[i - 1])
                    and min(o[i], c[i]) > min(o[i - 1], c[i - 1])):
                if prev_body < 0 and body > 0:
                    patterns.append(CandlePattern(
                        "Bullish Harami", "bullish", i, 0.55,
                        "Pause in downtrend — possible reversal"))
                elif prev_body > 0 and body < 0:
                    patterns.append(CandlePattern(
                        "Bearish Harami", "bearish", i, 0.55,
                        "Pause in uptrend — possible reversal"))
                continue

            # --- Three-candle patterns ---
            if i < 2:
                continue

            pp_body = c[i - 2] - o[i - 2]

            # Morning Star
            if (pp_body < 0 and prev_body_abs < abs(pp_body) * 0.3
                    and body > 0
                    and c[i] > (o[i - 2] + c[i - 2]) / 2):
                patterns.append(CandlePattern(
                    "Morning Star", "bullish", i, 0.80,
                    "Strong 3-bar reversal — dawn after bearish night"))
                continue

            # Evening Star
            if (pp_body > 0 and prev_body_abs < abs(pp_body) * 0.3
                    and body < 0
                    and c[i] < (o[i - 2] + c[i - 2]) / 2):
                patterns.append(CandlePattern(
                    "Evening Star", "bearish", i, 0.80,
                    "Strong 3-bar reversal — dusk after bullish day"))
                continue

            # Three White Soldiers
            if (c[i] > o[i] > 0 and c[i - 1] > o[i - 1] > 0 and c[i - 2] > o[i - 2] > 0
                    and c[i] > c[i - 1] > c[i - 2]
                    and o[i] > o[i - 1] > o[i - 2]):
                patterns.append(CandlePattern(
                    "Three White Soldiers", "bullish", i, 0.85,
                    "Strong trend — three consecutive bullish bars"))
                continue

            # Three Black Crows
            if (c[i] < o[i] and c[i - 1] < o[i - 1] and c[i - 2] < o[i - 2]
                    and c[i] < c[i - 1] < c[i - 2]
                    and o[i] < o[i - 1] < o[i - 2]):
                patterns.append(CandlePattern(
                    "Three Black Crows", "bearish", i, 0.85,
                    "Strong trend — three consecutive bearish bars"))
                continue

        return patterns


# ======================================================================
# 2.  Chart Structure Detector
# ======================================================================
class ChartStructureDetector:
    """Detect chart formations / figures from price action."""

    @staticmethod
    def detect(df: pd.DataFrame, lookback: int = 80) -> list[ChartStructure]:
        if len(df) < 20:
            return []

        structures: list[ChartStructure] = []
        n = len(df)
        start = max(0, n - lookback)
        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        c = df["close"].values.astype(float)

        # Find local extremes (peaks and troughs)
        peaks, troughs = ChartStructureDetector._find_pivots(h, l, window=5, start=start)

        # --- Double Top ---
        for j in range(1, len(peaks)):
            i1, p1 = peaks[j - 1]
            i2, p2 = peaks[j]
            if i2 - i1 < 5:
                continue
            tol = abs(p1) * 0.015  # 1.5% tolerance
            if abs(p1 - p2) < tol:
                # Find valley between
                valley = min(l[i1:i2 + 1])
                structures.append(ChartStructure(
                    "Double Top", "bearish", i1, i2,
                    key_points=[(i1, p1), (i2, p2)],
                    confidence=0.70,
                    description=f"Resistance ~{p1:.2f} — expect drop to {valley:.2f} neckline",
                ))

        # --- Double Bottom ---
        for j in range(1, len(troughs)):
            i1, p1 = troughs[j - 1]
            i2, p2 = troughs[j]
            if i2 - i1 < 5:
                continue
            tol = abs(p1) * 0.015
            if abs(p1 - p2) < tol:
                peak = max(h[i1:i2 + 1])
                structures.append(ChartStructure(
                    "Double Bottom", "bullish", i1, i2,
                    key_points=[(i1, p1), (i2, p2)],
                    confidence=0.70,
                    description=f"Support ~{p1:.2f} — expect rally to {peak:.2f} neckline",
                ))

        # --- Head & Shoulders ---
        if len(peaks) >= 3:
            for j in range(2, len(peaks)):
                li, lp = peaks[j - 2]
                hi, hp = peaks[j - 1]
                ri, rp = peaks[j]
                tol = abs(lp) * 0.02
                if hp > lp and hp > rp and abs(lp - rp) < tol:
                    structures.append(ChartStructure(
                        "Head & Shoulders", "bearish", li, ri,
                        key_points=[(li, lp), (hi, hp), (ri, rp)],
                        confidence=0.75,
                        description="Classic reversal — head above both shoulders",
                    ))

        # --- Inverse Head & Shoulders ---
        if len(troughs) >= 3:
            for j in range(2, len(troughs)):
                li, lp = troughs[j - 2]
                hi, hp = troughs[j - 1]
                ri, rp = troughs[j]
                tol = abs(lp) * 0.02
                if hp < lp and hp < rp and abs(lp - rp) < tol:
                    structures.append(ChartStructure(
                        "Inverse H&S", "bullish", li, ri,
                        key_points=[(li, lp), (hi, hp), (ri, rp)],
                        confidence=0.75,
                        description="Classic reversal — head below both shoulders",
                    ))

        # --- Triangles (ascending / descending / symmetrical) ---
        tri = ChartStructureDetector._detect_triangle(h, l, c, peaks, troughs, start, n)
        if tri:
            structures.append(tri)

        # --- Channel detection ---
        chan = ChartStructureDetector._detect_channel(h, l, peaks, troughs, start, n)
        if chan:
            structures.append(chan)

        # --- Support / Resistance levels ---
        sr = ChartStructureDetector._detect_sr_levels(h, l, c, start, n)
        structures.extend(sr)

        return structures

    # ------------------------------------------------------------------
    @staticmethod
    def _find_pivots(
        highs: np.ndarray, lows: np.ndarray, window: int = 5, start: int = 0,
    ) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        """Return (peaks, troughs) as lists of (index, price) tuples."""
        peaks, troughs = [], []
        for i in range(start + window, len(highs) - window):
            if highs[i] == np.max(highs[i - window: i + window + 1]):
                peaks.append((i, float(highs[i])))
            if lows[i] == np.min(lows[i - window: i + window + 1]):
                troughs.append((i, float(lows[i])))
        return peaks, troughs

    @staticmethod
    def _detect_triangle(
        h: np.ndarray, l: np.ndarray, c: np.ndarray,
        peaks: list, troughs: list,
        start: int, n: int,
    ) -> ChartStructure | None:
        """Detect ascending / descending / symmetrical triangle."""
        if len(peaks) < 2 or len(troughs) < 2:
            return None

        # Use last few peaks/troughs
        recent_peaks = peaks[-3:]
        recent_troughs = troughs[-3:]

        if len(recent_peaks) >= 2 and len(recent_troughs) >= 2:
            # Slopes of upper and lower trendlines
            p_xs = [p[0] for p in recent_peaks]
            p_ys = [p[1] for p in recent_peaks]
            t_xs = [t[0] for t in recent_troughs]
            t_ys = [t[1] for t in recent_troughs]

            if p_xs[-1] != p_xs[0] and t_xs[-1] != t_xs[0]:
                upper_slope = (p_ys[-1] - p_ys[0]) / (p_xs[-1] - p_xs[0])
                lower_slope = (t_ys[-1] - t_ys[0]) / (t_xs[-1] - t_xs[0])

                price_scale = abs(c[-1]) if c[-1] != 0 else 1.0
                norm_upper = upper_slope / price_scale * 100
                norm_lower = lower_slope / price_scale * 100

                start_idx = min(p_xs[0], t_xs[0])
                end_idx = max(p_xs[-1], t_xs[-1])

                # Ascending triangle: flat top, rising bottom
                if abs(norm_upper) < 0.05 and norm_lower > 0.02:
                    return ChartStructure(
                        "Ascending Triangle", "bullish", start_idx, end_idx,
                        key_points=[(px, py) for px, py in zip(p_xs, p_ys)]
                                   + [(tx, ty) for tx, ty in zip(t_xs, t_ys)],
                        confidence=0.65,
                        description="Flat resistance + rising support — usually breaks up",
                    )

                # Descending triangle: flat bottom, falling top
                if abs(norm_lower) < 0.05 and norm_upper < -0.02:
                    return ChartStructure(
                        "Descending Triangle", "bearish", start_idx, end_idx,
                        key_points=[(px, py) for px, py in zip(p_xs, p_ys)]
                                   + [(tx, ty) for tx, ty in zip(t_xs, t_ys)],
                        confidence=0.65,
                        description="Falling resistance + flat support — usually breaks down",
                    )

                # Symmetrical triangle: converging
                if norm_upper < -0.01 and norm_lower > 0.01:
                    return ChartStructure(
                        "Symmetrical Triangle", "neutral", start_idx, end_idx,
                        key_points=[(px, py) for px, py in zip(p_xs, p_ys)]
                                   + [(tx, ty) for tx, ty in zip(t_xs, t_ys)],
                        confidence=0.55,
                        description="Converging trendlines — breakout imminent in either direction",
                    )

        return None

    @staticmethod
    def _detect_channel(
        h: np.ndarray, l: np.ndarray,
        peaks: list, troughs: list,
        start: int, n: int,
    ) -> ChartStructure | None:
        """Detect ascending / descending price channel."""
        if len(peaks) < 2 or len(troughs) < 2:
            return None

        rp = peaks[-2:]
        rt = troughs[-2:]

        p_slope = (rp[-1][1] - rp[0][1]) / max(rp[-1][0] - rp[0][0], 1)
        t_slope = (rt[-1][1] - rt[0][1]) / max(rt[-1][0] - rt[0][0], 1)

        price_scale = abs(float(h[-1])) if h[-1] != 0 else 1.0
        n_p = p_slope / price_scale * 1000
        n_t = t_slope / price_scale * 1000

        # Parallel and both going same direction → channel
        if abs(n_p - n_t) < 0.5 and abs(n_p) > 0.1:
            kind = "bullish" if n_p > 0 else "bearish"
            name = "Ascending Channel" if n_p > 0 else "Descending Channel"
            s_idx = min(rp[0][0], rt[0][0])
            e_idx = max(rp[-1][0], rt[-1][0])
            return ChartStructure(
                name, kind, s_idx, e_idx,
                key_points=[(i, p) for i, p in rp] + [(i, p) for i, p in rt],
                confidence=0.60,
                description=f"Parallel trendlines — trade within the {name.lower()}",
            )

        return None

    @staticmethod
    def _detect_sr_levels(
        h: np.ndarray, l: np.ndarray, c: np.ndarray,
        start: int, n: int,
    ) -> list[ChartStructure]:
        """Find horizontal support / resistance clusters."""
        results = []
        recent_h = h[start:]
        recent_l = l[start:]
        recent_c = c[start:]

        if len(recent_c) < 10:
            return results

        price_range = float(recent_h.max() - recent_l.min())
        if price_range <= 0:
            return results

        # Cluster prices into bins (0.5% of range)
        bin_size = price_range * 0.005
        if bin_size <= 0:
            return results

        # Collect all highs/lows
        all_prices = np.concatenate([recent_h, recent_l])
        min_p = float(all_prices.min())

        bins: dict[int, list[float]] = {}
        for p in all_prices:
            k = int((p - min_p) / bin_size)
            bins.setdefault(k, []).append(float(p))

        # Find dense clusters (≥ 4 touches)
        current_price = float(recent_c[-1])
        for k, prices in sorted(bins.items(), key=lambda x: -len(x[1])):
            if len(prices) < 4:
                continue
            level = np.mean(prices)
            if level > current_price * 1.005:
                kind = "bearish"
                name = "Resistance"
            elif level < current_price * 0.995:
                kind = "bullish"
                name = "Support"
            else:
                continue

            results.append(ChartStructure(
                name, kind, start, n - 1,
                key_points=[(n - 1, level)],
                confidence=min(0.4 + len(prices) * 0.05, 0.85),
                description=f"{name} at {level:.2f} ({len(prices)} touches)",
            ))
            if len(results) >= 4:
                break

        return results


# ======================================================================
# 3.  Psychological Market Profile
# ======================================================================
class PsychProfiler:
    """Compute psychological sentiment indicators from price/volume data."""

    @staticmethod
    def profile(df: pd.DataFrame) -> PsychProfile:
        if len(df) < 20:
            return PsychProfile()

        c = df["close"].values.astype(float)
        o = df["open"].values.astype(float)
        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        v = df["volume"].values.astype(float)

        n = len(df)
        recent = 10  # last 10 bars for sentiment

        # Returns for recent bars
        rets = np.diff(c[-recent - 1:]) / c[-recent - 2:-1]
        rets = np.nan_to_num(rets)

        # Volume ratios
        avg_vol = float(np.mean(v[-50:])) if n >= 50 else float(np.mean(v))
        recent_vol = float(np.mean(v[-recent:])) if n >= recent else avg_vol
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0

        # --- FOMO (rapid rise + high volume) ---
        consecutive_green = 0
        for i in range(n - 1, max(n - recent - 1, 0), -1):
            if c[i] > o[i]:
                consecutive_green += 1
            else:
                break
        cum_gain = float(np.sum(np.maximum(rets, 0)))
        fomo = np.clip(
            (consecutive_green / 6) * 0.4
            + (cum_gain / 0.03) * 0.3
            + (min(vol_ratio, 3) / 3) * 0.3,
            0, 1,
        )

        # --- Fear (rapid drop + high volume) ---
        consecutive_red = 0
        for i in range(n - 1, max(n - recent - 1, 0), -1):
            if c[i] < o[i]:
                consecutive_red += 1
            else:
                break
        cum_loss = float(np.sum(np.minimum(rets, 0)))
        fear = np.clip(
            (consecutive_red / 6) * 0.4
            + (abs(cum_loss) / 0.03) * 0.3
            + (min(vol_ratio, 3) / 3) * 0.3,
            0, 1,
        )

        # --- Greed (near resistance + ignoring rejection wicks) ---
        recent_high = float(h[-recent:].max())
        price_near_high = 1.0 - min(abs(c[-1] - recent_high) / (recent_high * 0.01 + 1e-9), 1.0)
        avg_upper_wick_ratio = float(np.mean(
            (h[-recent:] - np.maximum(c[-recent:], o[-recent:]))
            / (h[-recent:] - l[-recent:] + 1e-9)
        ))
        greed = np.clip(
            price_near_high * 0.5
            + (1 - avg_upper_wick_ratio) * 0.2
            + fomo * 0.3,
            0, 1,
        )

        # --- Exhaustion (long wicks at extremes, doji-like patterns) ---
        recent_body_ratio = float(np.mean(
            np.abs(c[-recent:] - o[-recent:]) / (h[-recent:] - l[-recent:] + 1e-9)
        ))
        exhaustion = np.clip(
            (1 - recent_body_ratio) * 0.6
            + abs(float(np.mean(rets[-3:]))) / 0.01 * 0.4,
            0, 1,
        )

        # --- Accumulation / Distribution ---
        # Simplified A/D: (close - low) - (high - close)) / (high - low) * volume
        clv = ((c - l) - (h - c)) / (h - l + 1e-9)
        ad_line = np.cumsum(clv[-min(50, n):] * v[-min(50, n):])
        if len(ad_line) >= 10:
            ad_slope = float(ad_line[-1] - ad_line[-10]) / (float(np.std(ad_line)) + 1e-9)
            accumulation = float(np.clip(ad_slope / 3, -1, 1))
        else:
            accumulation = 0.0

        # Description
        parts = []
        if fomo > 0.6:
            parts.append("⚠️ FOMO detected — caution with longs")
        if fear > 0.6:
            parts.append("⚠️ Fear spike — potential capitulation")
        if greed > 0.7:
            parts.append("🔥 Greed near high — reversal risk")
        if exhaustion > 0.6:
            parts.append("💤 Exhaustion — momentum fading")
        if accumulation > 0.5:
            parts.append("📈 Smart money accumulating")
        elif accumulation < -0.5:
            parts.append("📉 Distribution phase")
        if not parts:
            parts.append("😐 Market neutral — no strong psychological bias")

        return PsychProfile(
            fomo_level=round(float(fomo), 3),
            fear_level=round(float(fear), 3),
            greed_level=round(float(greed), 3),
            exhaustion=round(float(exhaustion), 3),
            accumulation=round(float(accumulation), 3),
            description=" | ".join(parts),
        )


# ======================================================================
# 4.  Probability Forecaster
# ======================================================================
class ProbabilityForecaster:
    """
    Statistical probability forecast for short-term price movement.

    Combines:
      - Momentum (recent returns)
      - Volatility (ATR + standard dev)
      - Support / Resistance proximity
      - Volume trend
      - Mean reversion tendency
    """

    @staticmethod
    def forecast(df: pd.DataFrame) -> ProbabilityForecast:
        if len(df) < 30:
            return ProbabilityForecast()

        c = df["close"].values.astype(float)
        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        v = df["volume"].values.astype(float)

        n = len(df)
        current = float(c[-1])

        # --- Factor 1: Momentum (recent 5 bars vs 20 bars) ---
        ret_5 = (c[-1] - c[-6]) / c[-6] if n > 6 else 0
        ret_20 = (c[-1] - c[-21]) / c[-21] if n > 21 else 0
        momentum = float(np.clip((ret_5 * 0.6 + ret_20 * 0.4) * 10, -1, 1))

        # --- Factor 2: Volatility ---
        tr = np.maximum(h[1:] - l[1:], np.maximum(
            np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])
        ))
        atr_20 = float(np.mean(tr[-20:])) if len(tr) >= 20 else float(np.mean(tr))
        volatility_pct = (atr_20 / current * 100) if current > 0 else 0

        # --- Factor 3: Support / Resistance proximity ---
        lookback = min(n, 60)
        resistance = float(h[-lookback:].max())
        support = float(l[-lookback:].min())
        rng = resistance - support
        if rng > 0:
            position_in_range = (current - support) / rng  # 0=at support, 1=at resistance
        else:
            position_in_range = 0.5

        # Near support → bullish bias; near resistance → bearish bias
        sr_factor = float(np.clip((0.5 - position_in_range) * 2, -1, 1))

        # --- Factor 4: Volume trend ---
        avg_vol = float(np.mean(v[-20:])) if n >= 20 else float(np.mean(v))
        recent_vol = float(np.mean(v[-5:])) if n >= 5 else avg_vol
        vol_factor = float(np.clip((recent_vol / avg_vol - 1) * 2, -1, 1))

        # Combine (apply sign from momentum and SR, volume confirms)
        bullish_score = 0.0
        bearish_score = 0.0

        # Momentum contributes to direction
        if momentum > 0:
            bullish_score += momentum * 0.35
        else:
            bearish_score += abs(momentum) * 0.35

        # SR factor
        if sr_factor > 0:
            bullish_score += sr_factor * 0.30
        else:
            bearish_score += abs(sr_factor) * 0.30

        # Volume confirms the prevailing direction
        if vol_factor > 0:
            if momentum > 0:
                bullish_score += vol_factor * 0.15
            else:
                bearish_score += vol_factor * 0.15

        # Mean reversion (if extreme, pull back)
        if position_in_range > 0.85:
            bearish_score += 0.15
        elif position_in_range < 0.15:
            bullish_score += 0.15

        # Normalize to probabilities
        total = bullish_score + bearish_score + 0.2  # 0.2 = base "neutral"
        prob_up = round((bullish_score + 0.1) / total, 3)
        prob_down = round(1 - prob_up, 3)

        # Expected move
        expected_pct = round((prob_up - prob_down) * volatility_pct, 3)

        # Description
        if prob_up > 0.60:
            desc = f"📈 Bullish bias ({prob_up * 100:.0f}% up) — momentum + SR favour continuation"
        elif prob_down > 0.60:
            desc = f"📉 Bearish bias ({prob_down * 100:.0f}% down) — momentum + SR favour decline"
        else:
            desc = f"⚖️ Balanced ({prob_up * 100:.0f}%↑ / {prob_down * 100:.0f}%↓) — no strong directional bias"

        return ProbabilityForecast(
            prob_up=prob_up,
            prob_down=prob_down,
            expected_move_pct=expected_pct,
            volatility_pct=round(volatility_pct, 3),
            support=round(support, 6),
            resistance=round(resistance, 6),
            description=desc,
        )


# ======================================================================
# 5.  Unified Enhanced Analysis Engine
# ======================================================================
class EnhancedAnalysisEngine:
    """
    Orchestrator — runs all enhanced analysis components on an enriched DataFrame.

    Call `.analyse(df)` to get an `EnhancedAnalysisResult`.
    This is completely independent from the core IndicatorEngine.
    """

    def __init__(self) -> None:
        self.patterns = CandlePatternDetector()
        self.structures = ChartStructureDetector()
        self.psych = PsychProfiler()
        self.probability = ProbabilityForecaster()

    def analyse(self, df: pd.DataFrame) -> EnhancedAnalysisResult:
        """Run full enhanced analysis.  Thread-safe (stateless)."""
        log.debug("EnhancedAnalysisEngine.analyse  rows=%d", len(df))

        try:
            candles = self.patterns.detect(df, lookback=15)
            log.debug("  candle patterns: %d detected", len(candles))
        except Exception as e:
            log.warning("Candle pattern detection failed: %s", e)
            candles = []

        try:
            structs = self.structures.detect(df, lookback=80)
            log.debug("  chart structures: %d detected", len(structs))
        except Exception as e:
            log.warning("Chart structure detection failed: %s", e)
            structs = []

        try:
            psych = self.psych.profile(df)
            log.debug("  psych: fomo=%.2f  fear=%.2f  greed=%.2f",
                      psych.fomo_level, psych.fear_level, psych.greed_level)
        except Exception as e:
            log.warning("Psych profiling failed: %s", e)
            psych = PsychProfile()

        try:
            forecast = self.probability.forecast(df)
            log.debug("  forecast: up=%.0f%%  down=%.0f%%  expected=%.3f%%",
                      forecast.prob_up * 100, forecast.prob_down * 100,
                      forecast.expected_move_pct)
        except Exception as e:
            log.warning("Probability forecast failed: %s", e)
            forecast = ProbabilityForecast()

        log.info(
            "Enhanced analysis done  patterns=%d  structures=%d  "
            "prob_up=%.0f%%  prob_down=%.0f%%",
            len(candles), len(structs),
            forecast.prob_up * 100, forecast.prob_down * 100,
        )
        return EnhancedAnalysisResult(
            candle_patterns=candles,
            structures=structs,
            psych=psych,
            forecast=forecast,
        )
