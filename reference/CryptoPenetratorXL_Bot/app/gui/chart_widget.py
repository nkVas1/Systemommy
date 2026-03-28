"""
CryptoPenetratorXL — Candlestick Chart Widget  v2.2

Professional matplotlib-based chart with Japanese candles +
indicator sub-plots (Volume, Stochastic, MACD, CCI).
Embeds in PyQt6 via FigureCanvasQTAgg.

Features:
  - "Ideal Scenario" overlay: semi-transparent zones & annotations
    showing what conditions would create a good LONG / SHORT entry.
  - Signal markers: historical signal arrows on the price chart.
"""

from __future__ import annotations

from typing import Any

import matplotlib
matplotlib.use("QtAgg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch

from app.core.constants import (
    CCI_OVERBOUGHT,
    CCI_OVERSOLD,
    STOCH_OVERBOUGHT,
    STOCH_OVERSOLD,
    Signal,
)

# Late import to avoid circular dependency — used only for type hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.analysis.enhanced_analysis import EnhancedAnalysisResult


# Colour palette
BG        = "#0d1117"
PANEL_BG  = "#0d1117"
GRID      = "#1c2128"
TEXT      = "#8b949e"
BULL      = "#3fb950"
BEAR      = "#f85149"
BLUE      = "#58a6ff"
YELLOW    = "#d29922"
PURPLE    = "#bc8cff"
CYAN      = "#39d2c0"

# Ideal-scenario specific
IDEAL_LONG  = "#3fb950"
IDEAL_SHORT = "#f85149"
IDEAL_ALPHA = 0.07
ZONE_ALPHA  = 0.13
ANNOT_BG    = "#0d1117"

# Enhanced analysis overlay
ENH_PAT_BULL = "#3fb95088"
ENH_PAT_BEAR = "#f8514988"
ENH_STRUCT   = "#58a6ff"
ENH_PROB_UP  = "#3fb950"
ENH_PROB_DN  = "#f85149"

# Crosshair indicator labels (simple Unicode markers for cross-platform compat)
_LBL_OHLC  = "■ OHLC"
_LBL_VOL   = "■ Vol"
_LBL_STOCH = "■ Stoch"
_LBL_MACD  = "■ MACD"
_LBL_CCI   = "■ CCI"


class ChartWidget(FigureCanvas):
    """
    Matplotlib canvas with 5 sub-plots:
        1. Candlestick + price
        2. Volume bars
        3. Stochastic %K/%D
        4. MACD + histogram
        5. CCI

    Supports overlays:
        - Ideal Scenario (toggle)
        - Signal history markers
    """

    def __init__(self, parent=None, width: int = 12, height: int = 9):
        self.fig = Figure(figsize=(width, height), dpi=100, facecolor=BG)
        super().__init__(self.fig)
        self.setParent(parent)
        self._setup_axes()

        # Overlay state
        self._show_ideal = False
        self._show_enhanced = False
        self._enhanced_data: "EnhancedAnalysisResult | None" = None
        self._signal_markers: list[dict] = []   # [{timestamp, price, signal}, ...]
        self._active_trade: dict | None = None   # paper/live position for overlay

        # Price precision derived from exchange tick size (set externally)
        self._tick_size: float = 0.0

        # Interactive state (crosshair, percentage measurement)
        self._last_df: pd.DataFrame | None = None
        self._last_x: np.ndarray | None = None
        self._crosshair_enabled: bool = True      # toggled via settings
        self._crosshair_annotations: list = []
        self._pct_anchor_price: float | None = None
        self._pct_line = None
        self._pct_annotation = None
        self._mid_pressed = False
        # Cached background for blitting (set after each full draw)
        self._blit_bg = None

        self._connect_events()

    # ==================================================================
    # Axes setup
    # ==================================================================
    def _setup_axes(self) -> None:
        """Create the 5-panel grid layout."""
        gs = self.fig.add_gridspec(
            5, 1,
            height_ratios=[4, 1, 1, 1, 1],
            hspace=0.05,
        )
        self.ax_price = self.fig.add_subplot(gs[0])
        self.ax_vol   = self.fig.add_subplot(gs[1], sharex=self.ax_price)
        self.ax_stoch = self.fig.add_subplot(gs[2], sharex=self.ax_price)
        self.ax_macd  = self.fig.add_subplot(gs[3], sharex=self.ax_price)
        self.ax_cci   = self.fig.add_subplot(gs[4], sharex=self.ax_price)

        for ax in (self.ax_price, self.ax_vol, self.ax_stoch, self.ax_macd, self.ax_cci):
            ax.set_facecolor(PANEL_BG)
            ax.tick_params(colors=TEXT, labelsize=8)
            ax.grid(True, color=GRID, linewidth=0.3, alpha=0.5)
            for spine in ax.spines.values():
                spine.set_color(GRID)

        # Hide x labels except bottom
        for ax in (self.ax_price, self.ax_vol, self.ax_stoch, self.ax_macd):
            plt.setp(ax.get_xticklabels(), visible=False)

        self.ax_cci.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        self.ax_cci.tick_params(axis="x", rotation=30)

    # ==================================================================
    # Public API
    # ==================================================================
    def toggle_ideal_scenario(self, show: bool) -> None:
        """Enable / disable the Ideal Scenario overlay."""
        self._show_ideal = show

    def toggle_enhanced(self, show: bool) -> None:
        """Enable / disable the Enhanced Analysis overlay."""
        self._show_enhanced = show

    def set_enhanced_data(self, data: "EnhancedAnalysisResult | None") -> None:
        """Set enhanced analysis data for overlay rendering."""
        self._enhanced_data = data

    def set_signal_markers(self, markers: list[dict]) -> None:
        """Set signal-history markers to draw on the price chart.

        Each dict: {timestamp: datetime-like, price: float, signal: Signal}
        """
        self._signal_markers = markers

    def set_active_trade(self, trade: dict | None) -> None:
        """Set / clear the active trade overlay on the price chart.

        *trade* must contain: symbol, side, entry_price, mark_price,
        unrealised_pnl, tp (optional), sl (optional).
        Pass *None* to clear.
        """
        self._active_trade = trade

    def set_tick_size(self, tick_size: float) -> None:
        """Set the instrument tick size for proper price formatting."""
        self._tick_size = tick_size

    def toggle_crosshair(self, enabled: bool) -> None:
        """Enable / disable the interactive crosshair overlay."""
        self._crosshair_enabled = enabled
        if not enabled:
            self._clear_crosshair()
            self.draw_idle()

    @property
    def crosshair_enabled(self) -> bool:
        return self._crosshair_enabled

    # ==================================================================
    # Interactive event handling (crosshair + percentage measurement)
    # ==================================================================
    def _connect_events(self) -> None:
        """Wire up matplotlib canvas events for interactivity."""
        self.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.mpl_connect("button_press_event", self._on_mouse_press)
        self.mpl_connect("button_release_event", self._on_mouse_release)

    def _price_fmt(self, price: float) -> str:
        """Format a price using tick-size precision (helper)."""
        import math as _m
        if self._tick_size > 0:
            prec = max(0, -int(_m.floor(_m.log10(self._tick_size))))
            return f"{price:,.{prec}f}"
        if price >= 1:
            return f"{price:,.2f}"
        if price == 0:
            return "0.00"
        sig = max(2, -int(_m.floor(_m.log10(abs(price)))) + 2)
        return f"{price:.{sig}f}"

    def _on_mouse_move(self, event) -> None:
        """Draw crosshair that snaps to the nearest candle.

        Uses restore_region / blit for smooth, low-latency rendering.
        """
        # Remove old crosshair artefacts first
        self._clear_crosshair()

        if not self._crosshair_enabled:
            return

        if event.inaxes is None or self._last_df is None or self._last_x is None:
            self.draw_idle()
            return

        if event.xdata is None:
            return

        df = self._last_df
        x = self._last_x
        if len(x) == 0:
            return

        # Find the nearest candle index
        idx = int(np.argmin(np.abs(x - event.xdata)))
        if idx < 0 or idx >= len(df):
            return
        snap_x = x[idx]

        # Draw vertical line on ALL sub-plots
        for ax in (self.ax_price, self.ax_vol, self.ax_stoch, self.ax_macd, self.ax_cci):
            vl = ax.axvline(snap_x, color="#ffffff", linewidth=0.5, linestyle=":", alpha=0.5, zorder=10)
            self._crosshair_annotations.append(vl)

        # Horizontal line on the hovered axis only
        hl = event.inaxes.axhline(event.ydata, color="#ffffff", linewidth=0.5, linestyle=":", alpha=0.5, zorder=10)
        self._crosshair_annotations.append(hl)

        # Build info annotation with visual mini-blocks per indicator group
        self._draw_info_blocks(idx, df)

        # Percentage measurement while middle-button is held
        if self._mid_pressed and self._pct_anchor_price is not None and event.inaxes == self.ax_price:
            anchor = self._pct_anchor_price
            current = event.ydata
            if anchor != 0:
                pct = (current - anchor) / anchor * 100
                sign = "+" if pct >= 0 else ""
                color = BULL if pct >= 0 else BEAR
                # Draw a line from anchor to current
                self._pct_line = self.ax_price.axhline(
                    anchor, color=color, linewidth=0.8, linestyle="-.", alpha=0.7, zorder=15,
                )
                self._crosshair_annotations.append(self._pct_line)

                # Shade between anchor and current price level
                lo, hi = min(anchor, current), max(anchor, current)
                span = self.ax_price.axhspan(lo, hi, alpha=0.08, color=color, zorder=1)
                self._crosshair_annotations.append(span)

                ann_pct = self.ax_price.annotate(
                    f" {sign}{pct:.2f}% ",
                    xy=(snap_x, current),
                    fontsize=10, color=color, fontweight="bold",
                    va="bottom" if pct >= 0 else "top",
                    bbox=dict(boxstyle="round,pad=0.25", fc="#0d1117", ec=color, alpha=0.9),
                    zorder=20,
                )
                self._crosshair_annotations.append(ann_pct)

        self.draw_idle()

    def _draw_info_blocks(self, idx: int, df: pd.DataFrame) -> None:
        """Draw crosshair info as visually-separated mini-blocks for each indicator group."""
        # ── Price ─────────────────────────────────────
        o_val = float(df["open"].iloc[idx])
        h_val = float(df["high"].iloc[idx])
        l_val = float(df["low"].iloc[idx])
        c_val = float(df["close"].iloc[idx])
        change_pct = (c_val - o_val) / o_val * 100 if o_val != 0 else 0.0
        price_color = BULL if c_val >= o_val else BEAR

        y_pos = 0.98   # Start from top-left
        x_pos = 0.01

        # -- Price block --
        price_text = (
            f" {_LBL_OHLC}\n"
            f" O {self._price_fmt(o_val)}   H {self._price_fmt(h_val)}\n"
            f" L {self._price_fmt(l_val)}   C {self._price_fmt(c_val)}  ({change_pct:+.2f}%)"
        )
        ann_price = self.ax_price.annotate(
            price_text,
            xy=(x_pos, y_pos), xycoords="axes fraction",
            fontsize=7, color=price_color, fontfamily="monospace",
            va="top", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", fc="#0d1117", ec=price_color, alpha=0.90, linewidth=0.8),
            zorder=20,
        )
        self._crosshair_annotations.append(ann_price)

        # -- Volume block --
        vol_val = float(df["volume"].iloc[idx])
        vol_ma_text = ""
        if "VOL_MA" in df.columns and not np.isnan(df["VOL_MA"].iloc[idx]):
            vol_ma = float(df["VOL_MA"].iloc[idx])
            vol_ratio = vol_val / vol_ma if vol_ma > 0 else 0
            vol_ma_text = f"   MA {vol_ma:,.0f}  (×{vol_ratio:.1f})"
        vol_text = f" {_LBL_VOL} {vol_val:,.0f}{vol_ma_text}"
        ann_vol = self.ax_price.annotate(
            vol_text,
            xy=(x_pos, y_pos - 0.16), xycoords="axes fraction",
            fontsize=7, color=YELLOW, fontfamily="monospace",
            va="top", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", fc="#0d1117", ec="#30363d", alpha=0.90, linewidth=0.8),
            zorder=20,
        )
        self._crosshair_annotations.append(ann_vol)

        # -- Stochastic block --
        if "STOCH_K" in df.columns and not np.isnan(df["STOCH_K"].iloc[idx]):
            k_val = float(df["STOCH_K"].iloc[idx])
            d_val = float(df["STOCH_D"].iloc[idx])
            if k_val <= STOCH_OVERSOLD:
                zone = "OVERSOLD"
                stoch_color = BULL
            elif k_val >= STOCH_OVERBOUGHT:
                zone = "OVERBOUGHT"
                stoch_color = BEAR
            else:
                zone = "NEUTRAL"
                stoch_color = TEXT
            stoch_text = f" {_LBL_STOCH}  %K {k_val:.1f}  %D {d_val:.1f}  [{zone}]"
            ann_stoch = self.ax_price.annotate(
                stoch_text,
                xy=(x_pos, y_pos - 0.24), xycoords="axes fraction",
                fontsize=7, color=stoch_color, fontfamily="monospace",
                va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.3", fc="#0d1117", ec="#30363d", alpha=0.90, linewidth=0.8),
                zorder=20,
            )
            self._crosshair_annotations.append(ann_stoch)

        # -- MACD block --
        if "MACD" in df.columns and not np.isnan(df["MACD"].iloc[idx]):
            macd_val = float(df["MACD"].iloc[idx])
            sig_val = float(df["MACD_SIGNAL"].iloc[idx])
            hist_val = float(df["MACD_HIST"].iloc[idx]) if "MACD_HIST" in df.columns else 0
            macd_color = BULL if hist_val >= 0 else BEAR
            macd_text = f" {_LBL_MACD} {macd_val:.4f}  Sig {sig_val:.4f}  Hist {hist_val:+.4f}"
            ann_macd = self.ax_price.annotate(
                macd_text,
                xy=(x_pos, y_pos - 0.32), xycoords="axes fraction",
                fontsize=7, color=macd_color, fontfamily="monospace",
                va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.3", fc="#0d1117", ec="#30363d", alpha=0.90, linewidth=0.8),
                zorder=20,
            )
            self._crosshair_annotations.append(ann_macd)

        # -- CCI block --
        if "CCI" in df.columns and not np.isnan(df["CCI"].iloc[idx]):
            cci_val = float(df["CCI"].iloc[idx])
            if cci_val <= CCI_OVERSOLD:
                cci_zone = "OVERSOLD"
                cci_color = BULL
            elif cci_val >= CCI_OVERBOUGHT:
                cci_zone = "OVERBOUGHT"
                cci_color = BEAR
            else:
                cci_zone = "NEUTRAL"
                cci_color = CYAN
            cci_text = f" {_LBL_CCI} {cci_val:.1f}  [{cci_zone}]"
            ann_cci = self.ax_price.annotate(
                cci_text,
                xy=(x_pos, y_pos - 0.40), xycoords="axes fraction",
                fontsize=7, color=cci_color, fontfamily="monospace",
                va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.3", fc="#0d1117", ec="#30363d", alpha=0.90, linewidth=0.8),
                zorder=20,
            )
            self._crosshair_annotations.append(ann_cci)

    def _on_mouse_press(self, event) -> None:
        """Middle-button press → start percentage measurement."""
        if not self._crosshair_enabled:
            return
        if event.button == 2 and event.inaxes == self.ax_price:
            self._mid_pressed = True
            self._pct_anchor_price = event.ydata

    def _on_mouse_release(self, event) -> None:
        """Middle-button release → end percentage measurement."""
        if event.button == 2:
            self._mid_pressed = False
            self._pct_anchor_price = None
            self._clear_crosshair()
            self.draw_idle()

    def _clear_crosshair(self) -> None:
        """Remove all transient crosshair/annotation artists."""
        for art in self._crosshair_annotations:
            try:
                art.remove()
            except (ValueError, AttributeError):
                pass
        self._crosshair_annotations.clear()

    def update_chart(self, df: pd.DataFrame, symbol: str = "", timeframe: str = "") -> None:
        """Redraw the entire chart with new data."""
        if df is None or df.empty:
            return

        # Clear crosshair artefacts first (they reference old axes artists)
        self._crosshair_annotations.clear()

        # Clear
        for ax in (self.ax_price, self.ax_vol, self.ax_stoch, self.ax_macd, self.ax_cci):
            ax.clear()
            ax.set_facecolor(PANEL_BG)
            ax.grid(True, color=GRID, linewidth=0.3, alpha=0.5)
            for spine in ax.spines.values():
                spine.set_color(GRID)
            ax.tick_params(colors=TEXT, labelsize=8)

        dates = pd.to_datetime(df["timestamp"]) if "timestamp" in df.columns else df.index
        x = mdates.date2num(dates)

        # Store for interactive crosshair
        self._last_df = df.copy()
        self._last_x = x

        self._draw_candles(x, df)
        self._draw_volume(x, df)
        self._draw_stochastic(x, df)
        self._draw_macd(x, df)
        self._draw_cci(x, df)

        # Overlays
        if self._show_ideal:
            self._draw_ideal_overlay(x, df)
        if self._show_enhanced and self._enhanced_data is not None:
            self._draw_enhanced_overlay(x, df, self._enhanced_data)
        if self._signal_markers:
            self._draw_signal_markers_on_price(x, df)
        if self._active_trade is not None:
            self._draw_trade_overlay(x, df)

        # Title
        ideal_tag = "  [IDEAL SCENARIO]" if self._show_ideal else ""
        enhanced_tag = "  [🧠 ENHANCED]" if self._show_enhanced else ""
        self.ax_price.set_title(
            f"  {symbol}  {timeframe}{ideal_tag}{enhanced_tag}",
            loc="left", fontsize=12, color=BLUE, fontweight="bold", pad=8,
        )

        # Format x-axis
        plt.setp(self.ax_price.get_xticklabels(), visible=False)
        plt.setp(self.ax_vol.get_xticklabels(), visible=False)
        plt.setp(self.ax_stoch.get_xticklabels(), visible=False)
        plt.setp(self.ax_macd.get_xticklabels(), visible=False)
        self.ax_cci.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        self.ax_cci.tick_params(axis="x", rotation=30, labelsize=7)

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                self.fig.tight_layout(pad=0.5)
            except Exception:
                pass
        self.draw()

    # ==================================================================
    # Sub-plot renderers
    # ==================================================================
    def _draw_candles(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_price
        o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values

        width = 0.6 * (x[1] - x[0]) if len(x) > 1 else 0.001
        wick_width = width * 0.15

        colours = np.where(c >= o, BULL, BEAR)

        # Wicks
        for i in range(len(x)):
            ax.plot([x[i], x[i]], [l[i], h[i]], color=colours[i], linewidth=0.8)

        # Bodies
        body_bottom = np.minimum(o, c)
        body_height = np.abs(c - o)
        body_height = np.where(body_height < (h - l) * 0.005, (h - l) * 0.005, body_height)

        ax.bar(x, body_height, bottom=body_bottom, width=width, color=colours, edgecolor=colours, linewidth=0.5)

        # Current price line
        last_price = c[-1]
        ax.axhline(last_price, color=BLUE, linewidth=0.6, linestyle="--", alpha=0.5)
        ax.text(
            x[-1] + width * 2, last_price,
            f" {self._price_fmt(last_price)}",
            color=BLUE, fontsize=8, va="center",
        )

        ax.set_ylabel("Price", color=TEXT, fontsize=9)

    def _draw_volume(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_vol
        vol = df["volume"].values
        o, c = df["open"].values, df["close"].values
        colours = np.where(c >= o, BULL, BEAR)
        width = 0.6 * (x[1] - x[0]) if len(x) > 1 else 0.001

        ax.bar(x, vol, width=width, color=colours, alpha=0.6)

        if "VOL_MA" in df.columns:
            ax.plot(x, df["VOL_MA"].values, color=YELLOW, linewidth=1, alpha=0.8, label="MA(20)")

        ax.set_ylabel("Volume", color=TEXT, fontsize=9)
        ax.legend(loc="upper left", fontsize=7, framealpha=0.3, labelcolor=TEXT)

    def _draw_stochastic(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_stoch
        if "STOCH_K" not in df.columns:
            ax.text(0.5, 0.5, "No Stochastic data", transform=ax.transAxes, ha="center", color=TEXT)
            return

        ax.plot(x, df["STOCH_K"].values, color=BLUE, linewidth=1.2, label="%K")
        ax.plot(x, df["STOCH_D"].values, color=PURPLE, linewidth=1, linestyle="--", label="%D")

        ax.axhline(STOCH_OVERBOUGHT, color=BEAR, linewidth=0.5, linestyle=":", alpha=0.5)
        ax.axhline(STOCH_OVERSOLD, color=BULL, linewidth=0.5, linestyle=":", alpha=0.5)
        ax.axhline(50, color=TEXT, linewidth=0.3, linestyle=":", alpha=0.3)

        ax.fill_between(x, STOCH_OVERBOUGHT, 100, alpha=0.04, color=BEAR)
        ax.fill_between(x, 0, STOCH_OVERSOLD, alpha=0.04, color=BULL)

        ax.set_ylim(-5, 105)
        ax.set_ylabel("Stoch", color=TEXT, fontsize=9)
        ax.legend(loc="upper left", fontsize=7, framealpha=0.3, labelcolor=TEXT)

    def _draw_macd(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_macd
        if "MACD" not in df.columns:
            ax.text(0.5, 0.5, "No MACD data", transform=ax.transAxes, ha="center", color=TEXT)
            return

        macd = df["MACD"].values
        signal = df["MACD_SIGNAL"].values
        hist = df["MACD_HIST"].values

        # Histogram bars
        colours = np.where(hist >= 0, BULL, BEAR)
        width = 0.6 * (x[1] - x[0]) if len(x) > 1 else 0.001
        ax.bar(x, hist, width=width, color=colours, alpha=0.5)

        # Lines
        ax.plot(x, macd, color=BLUE, linewidth=1.2, label="MACD")
        ax.plot(x, signal, color=PURPLE, linewidth=1, linestyle="--", label="Signal")
        ax.axhline(0, color=TEXT, linewidth=0.3, linestyle=":", alpha=0.3)

        ax.set_ylabel("MACD", color=TEXT, fontsize=9)
        ax.legend(loc="upper left", fontsize=7, framealpha=0.3, labelcolor=TEXT)

    def _draw_cci(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_cci
        if "CCI" not in df.columns:
            ax.text(0.5, 0.5, "No CCI data", transform=ax.transAxes, ha="center", color=TEXT)
            return

        cci = df["CCI"].values
        ax.plot(x, cci, color=CYAN, linewidth=1.2, label="CCI(20)")

        ax.axhline(CCI_OVERBOUGHT, color=BEAR, linewidth=0.5, linestyle=":", alpha=0.5)
        ax.axhline(CCI_OVERSOLD, color=BULL, linewidth=0.5, linestyle=":", alpha=0.5)
        ax.axhline(0, color=TEXT, linewidth=0.3, linestyle=":", alpha=0.3)

        ax.fill_between(x, CCI_OVERBOUGHT, np.maximum(cci, CCI_OVERBOUGHT), alpha=0.06, color=BEAR)
        ax.fill_between(x, CCI_OVERSOLD, np.minimum(cci, CCI_OVERSOLD), alpha=0.06, color=BULL)

        ax.set_ylabel("CCI", color=TEXT, fontsize=9)
        ax.legend(loc="upper left", fontsize=7, framealpha=0.3, labelcolor=TEXT)

    # ==================================================================
    # Ideal Scenario Overlay
    # ==================================================================
    def _draw_ideal_overlay(self, x: np.ndarray, df: pd.DataFrame) -> None:
        """Draw semi-transparent zones + annotations on every sub-plot
        showing what indicator state would create a good LONG / SHORT entry.
        """
        self._ideal_price(x, df)
        self._ideal_stochastic(x, df)
        self._ideal_macd(x, df)
        self._ideal_cci(x, df)
        self._ideal_volume(x, df)

    # -- Price chart -------------------------------------------------
    def _ideal_price(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_price
        n = len(df)
        lookback = min(n, 50)
        recent = df.tail(lookback)

        # Dynamic support / resistance from rolling extremes
        support    = float(recent["low"].rolling(min(lookback, 20)).min().iloc[-1])
        resistance = float(recent["high"].rolling(min(lookback, 20)).max().iloc[-1])
        price_range = resistance - support
        if price_range <= 0:
            return

        # Long entry zone — band near support
        long_top = support + price_range * 0.15
        ax.axhspan(support, long_top, alpha=IDEAL_ALPHA, color=IDEAL_LONG, zorder=0)
        ax.axhline(support, color=IDEAL_LONG, linewidth=0.8, linestyle="--", alpha=0.35)

        # Short entry zone — band near resistance
        short_bot = resistance - price_range * 0.15
        ax.axhspan(short_bot, resistance, alpha=IDEAL_ALPHA, color=IDEAL_SHORT, zorder=0)
        ax.axhline(resistance, color=IDEAL_SHORT, linewidth=0.8, linestyle="--", alpha=0.35)

        # Annotations at right edge
        right_x = x[-1]
        bbox_kw = dict(boxstyle="round,pad=0.25", fc=ANNOT_BG, alpha=0.75)

        ax.annotate(
            "▲ IDEAL LONG", xy=(right_x, support),
            fontsize=7, color=IDEAL_LONG, fontweight="bold",
            bbox={**bbox_kw, "ec": IDEAL_LONG},
            xytext=(10, 8), textcoords="offset points",
        )
        ax.annotate(
            "▼ IDEAL SHORT", xy=(right_x, resistance),
            fontsize=7, color=IDEAL_SHORT, fontweight="bold",
            bbox={**bbox_kw, "ec": IDEAL_SHORT},
            xytext=(10, -14), textcoords="offset points",
        )

        # Mid-range "avoid" zone — very subtle
        mid = (support + resistance) / 2
        ax.axhline(mid, color=YELLOW, linewidth=0.5, linestyle=":", alpha=0.25)
        ax.annotate(
            "≈ MID-RANGE (avoid)", xy=(right_x, mid),
            fontsize=6, color=YELLOW, alpha=0.5,
            xytext=(10, 0), textcoords="offset points",
        )

    # -- Stochastic -------------------------------------------------
    def _ideal_stochastic(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_stoch
        if "STOCH_K" not in df.columns:
            return

        # Enhanced trigger zones
        ax.axhspan(0, STOCH_OVERSOLD, alpha=ZONE_ALPHA, color=IDEAL_LONG, zorder=0)
        ax.axhspan(STOCH_OVERBOUGHT, 100, alpha=ZONE_ALPHA, color=IDEAL_SHORT, zorder=0)

        # Right-edge labels
        bbox_kw = dict(boxstyle="round,pad=0.2", fc=ANNOT_BG, alpha=0.7)
        ax.annotate(
            "▲ LONG: K↗ crosses D in oversold",
            xy=(0.98, 0.12), xycoords="axes fraction", fontsize=6,
            color=IDEAL_LONG, ha="right", fontweight="bold",
            bbox={**bbox_kw, "ec": IDEAL_LONG},
        )
        ax.annotate(
            "▼ SHORT: K↘ crosses D in overbought",
            xy=(0.98, 0.88), xycoords="axes fraction", fontsize=6,
            color=IDEAL_SHORT, ha="right", fontweight="bold",
            bbox={**bbox_kw, "ec": IDEAL_SHORT},
        )

        # Projected ideal path from current values
        k = df["STOCH_K"].values
        d = df["STOCH_D"].values
        k_now, d_now = float(k[-1]), float(d[-1])
        step = (x[1] - x[0]) if len(x) > 1 else 0.001

        # Long projection: K dips to oversold, then crosses above D
        proj_x = [x[-1], x[-1] + step, x[-1] + step * 2, x[-1] + step * 3]
        target_low = min(k_now, STOCH_OVERSOLD - 2)
        proj_k_long = [k_now, max(target_low, 5), target_low + 8, target_low + 20]
        proj_d_long = [d_now, d_now * 0.8, target_low + 2, target_low + 12]
        ax.plot(proj_x, proj_k_long, color=IDEAL_LONG, linewidth=1, linestyle=":", alpha=0.35)
        ax.plot(proj_x, proj_d_long, color=PURPLE, linewidth=0.8, linestyle=":", alpha=0.25)

        # Short projection: K rises to overbought, then crosses below D
        target_hi = max(k_now, STOCH_OVERBOUGHT + 2)
        proj_k_short = [k_now, min(target_hi, 95), target_hi - 8, target_hi - 20]
        proj_d_short = [d_now, min(d_now * 1.1, 92) if d_now < 80 else 92, target_hi - 2, target_hi - 12]
        ax.plot(proj_x, proj_k_short, color=IDEAL_SHORT, linewidth=1, linestyle=":", alpha=0.35)
        ax.plot(proj_x, proj_d_short, color=PURPLE, linewidth=0.8, linestyle=":", alpha=0.25)

    # -- MACD -------------------------------------------------------
    def _ideal_macd(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_macd
        if "MACD" not in df.columns:
            return

        # Zone colours above / below zero
        ylim = ax.get_ylim()
        ax.axhspan(0, ylim[1], alpha=0.03, color=IDEAL_LONG, zorder=0)
        ax.axhspan(ylim[0], 0, alpha=0.03, color=IDEAL_SHORT, zorder=0)

        bbox_kw = dict(boxstyle="round,pad=0.2", fc=ANNOT_BG, alpha=0.7)

        ax.annotate(
            "▲ LONG: MACD crosses above Signal,\n   histogram turns positive",
            xy=(0.98, 0.85), xycoords="axes fraction", fontsize=6,
            color=IDEAL_LONG, ha="right",
            bbox={**bbox_kw, "ec": IDEAL_LONG},
        )
        ax.annotate(
            "▼ SHORT: MACD crosses below Signal,\n   histogram turns negative",
            xy=(0.98, 0.15), xycoords="axes fraction", fontsize=6,
            color=IDEAL_SHORT, ha="right",
            bbox={**bbox_kw, "ec": IDEAL_SHORT},
        )

        # Projected crossover ghost lines
        macd_v = df["MACD"].values
        sig_v  = df["MACD_SIGNAL"].values
        step   = (x[1] - x[0]) if len(x) > 1 else 0.001
        proj_x = [x[-1], x[-1] + step, x[-1] + step * 2]

        m, s = float(macd_v[-1]), float(sig_v[-1])
        gap = abs(m - s) if abs(m - s) > 0 else 1.0

        # Bullish crossover projection
        cross_target = s + gap * 0.5
        ax.plot(proj_x, [m, (m + cross_target) / 2, cross_target + gap * 0.3],
                color=IDEAL_LONG, linewidth=1, linestyle=":", alpha=0.35)
        ax.plot(proj_x, [s, s * 0.95, s * 0.9],
                color=PURPLE, linewidth=0.8, linestyle=":", alpha=0.25)

        # Bearish crossover projection
        cross_target_b = s - gap * 0.5
        ax.plot(proj_x, [m, (m + cross_target_b) / 2, cross_target_b - gap * 0.3],
                color=IDEAL_SHORT, linewidth=1, linestyle=":", alpha=0.35)

    # -- CCI --------------------------------------------------------
    def _ideal_cci(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_cci
        if "CCI" not in df.columns:
            return

        ylim = ax.get_ylim()
        # Enhanced extreme zones
        ax.axhspan(ylim[0], CCI_OVERSOLD, alpha=ZONE_ALPHA, color=IDEAL_LONG, zorder=0)
        ax.axhspan(CCI_OVERBOUGHT, ylim[1], alpha=ZONE_ALPHA, color=IDEAL_SHORT, zorder=0)

        bbox_kw = dict(boxstyle="round,pad=0.2", fc=ANNOT_BG, alpha=0.7)

        ax.annotate(
            "▲ LONG: CCI recovering from < −100",
            xy=(0.98, 0.10), xycoords="axes fraction", fontsize=6,
            color=IDEAL_LONG, ha="right", fontweight="bold",
            bbox={**bbox_kw, "ec": IDEAL_LONG},
        )
        ax.annotate(
            "▼ SHORT: CCI falling from > +100",
            xy=(0.98, 0.90), xycoords="axes fraction", fontsize=6,
            color=IDEAL_SHORT, ha="right", fontweight="bold",
            bbox={**bbox_kw, "ec": IDEAL_SHORT},
        )

        # Ghost projection
        cci_v = float(df["CCI"].values[-1])
        step = (x[1] - x[0]) if len(x) > 1 else 0.001
        proj_x = [x[-1], x[-1] + step, x[-1] + step * 2]

        # Long: CCI drops below -100 then recovers
        target_low = min(cci_v, CCI_OVERSOLD - 20)
        ax.plot(proj_x, [cci_v, target_low, target_low + 60],
                color=IDEAL_LONG, linewidth=1, linestyle=":", alpha=0.35)
        # Short: CCI rises above +100 then drops
        target_hi = max(cci_v, CCI_OVERBOUGHT + 20)
        ax.plot(proj_x, [cci_v, target_hi, target_hi - 60],
                color=IDEAL_SHORT, linewidth=1, linestyle=":", alpha=0.35)

    # -- Volume (spike indicator) ------------------------------------
    def _ideal_volume(self, x: np.ndarray, df: pd.DataFrame) -> None:
        ax = self.ax_vol
        if "VOL_MA" not in df.columns:
            return

        vol_ma = df["VOL_MA"].values
        if np.isnan(vol_ma[-1]) or vol_ma[-1] <= 0:
            return
        spike_level = float(vol_ma[-1]) * 1.5

        ax.axhline(spike_level, color=YELLOW, linewidth=0.8, linestyle="--", alpha=0.4)
        ax.annotate(
            "⚡ Volume spike (1.5× MA) confirms entry",
            xy=(0.98, 0.85), xycoords="axes fraction", fontsize=6,
            color=YELLOW, ha="right",
            bbox=dict(boxstyle="round,pad=0.2", fc=ANNOT_BG, ec=YELLOW, alpha=0.7),
        )

    # ==================================================================
    # Enhanced Analysis Overlay
    # ==================================================================
    def _draw_enhanced_overlay(self, x: np.ndarray, df: pd.DataFrame, data: "EnhancedAnalysisResult") -> None:
        """Draw enhanced analysis overlays on the price chart:
        - Candlestick pattern markers (▲/▼/◆ with labels)
        - Chart structure lines (triangles, H&S, double tops/bottoms, S/R)
        - Probability forecast bar at the right edge
        - Psych sentiment bar
        """
        self._enh_candle_patterns(x, df, data.candle_patterns)
        self._enh_chart_structures(x, df, data.structures)
        self._enh_probability_bar(x, df, data.forecast)
        self._enh_psych_bar(x, df, data.psych)

    # -- Candlestick patterns on price chart -------------------------
    def _enh_candle_patterns(self, x: np.ndarray, df: pd.DataFrame, patterns) -> None:
        ax = self.ax_price
        if not patterns:
            return

        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        rng = float(h.max() - l.min())
        offset = rng * 0.02

        for p in patterns:
            if p.bar_index < 0 or p.bar_index >= len(x):
                continue
            px = x[p.bar_index]

            if p.kind == "bullish":
                marker_y = float(l[p.bar_index]) - offset
                color = ENH_PAT_BULL
                marker = "▲"
                va = "top"
            elif p.kind == "bearish":
                marker_y = float(h[p.bar_index]) + offset
                color = ENH_PAT_BEAR
                marker = "▼"
                va = "bottom"
            else:
                marker_y = float((h[p.bar_index] + l[p.bar_index]) / 2)
                color = YELLOW
                marker = "◆"
                va = "center"

            # Small marker
            ax.annotate(
                marker, xy=(px, marker_y),
                fontsize=7, color=color, ha="center", va=va,
                fontweight="bold", alpha=0.85,
            )

            # Label only for high-confidence patterns (≥0.6)
            if p.confidence >= 0.6:
                label_offset = (0, -12) if p.kind == "bullish" else (0, 10)
                ax.annotate(
                    f"{p.name}", xy=(px, marker_y),
                    fontsize=5, color=color, ha="center", va=va,
                    xytext=label_offset, textcoords="offset points",
                    alpha=0.7,
                    bbox=dict(boxstyle="round,pad=0.15", fc=ANNOT_BG, ec=color, alpha=0.5),
                )

    # -- Chart structures (S/R lines, triangles, H&S) ----------------
    def _enh_chart_structures(self, x: np.ndarray, df: pd.DataFrame, structures) -> None:
        ax = self.ax_price
        if not structures:
            return

        for s in structures:
            color = ENH_PROB_UP if s.kind == "bullish" else ENH_PROB_DN if s.kind == "bearish" else ENH_STRUCT

            # Draw key points and connecting lines
            if s.name in ("Support", "Resistance") and s.key_points:
                # Horizontal S/R level
                level = s.key_points[0][1]
                ax.axhline(level, color=color, linewidth=0.9, linestyle="-.", alpha=0.5)
                ax.annotate(
                    f" {s.name} {level:,.2f} ({s.confidence:.0%})",
                    xy=(x[-1], level),
                    fontsize=6, color=color, ha="left", va="center",
                    xytext=(5, 0), textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=0.2", fc=ANNOT_BG, ec=color, alpha=0.65),
                )

            elif s.name in ("Double Top", "Double Bottom", "Head & Shoulders", "Inverse H&S"):
                # Draw points connected by lines
                pts = [(x[min(idx, len(x) - 1)], price) for idx, price in s.key_points if idx < len(x)]
                if len(pts) >= 2:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    ax.plot(xs, ys, color=color, linewidth=1.2, linestyle="--", alpha=0.6, marker="o", markersize=4)
                    # Label at midpoint
                    mid_x = xs[len(xs) // 2]
                    mid_y = max(ys) if s.kind == "bearish" else min(ys)
                    vert_off = 8 if s.kind == "bearish" else -8
                    ax.annotate(
                        f"{s.name} ({s.confidence:.0%})",
                        xy=(mid_x, mid_y),
                        fontsize=6, color=color, ha="center",
                        xytext=(0, vert_off), textcoords="offset points",
                        fontweight="bold", alpha=0.75,
                        bbox=dict(boxstyle="round,pad=0.2", fc=ANNOT_BG, ec=color, alpha=0.6),
                    )

            elif "Triangle" in s.name or "Channel" in s.name:
                # Draw trendlines using key_points
                if len(s.key_points) >= 4:
                    # First half = peaks/upper, second half = troughs/lower
                    half = len(s.key_points) // 2
                    upper = s.key_points[:half]
                    lower = s.key_points[half:]

                    ux = [x[min(idx, len(x) - 1)] for idx, _ in upper if idx < len(x)]
                    uy = [price for idx, price in upper if idx < len(x)]
                    lx = [x[min(idx, len(x) - 1)] for idx, _ in lower if idx < len(x)]
                    ly = [price for idx, price in lower if idx < len(x)]

                    if len(ux) >= 2:
                        ax.plot(ux, uy, color=color, linewidth=1.0, linestyle="--", alpha=0.5)
                    if len(lx) >= 2:
                        ax.plot(lx, ly, color=color, linewidth=1.0, linestyle="--", alpha=0.5)

                    # Label
                    label_x = x[min(s.end_idx, len(x) - 1)] if s.end_idx < len(x) else x[-1]
                    label_y = float(df["high"].values[-1])
                    ax.annotate(
                        f"{s.name} ({s.confidence:.0%})",
                        xy=(label_x, label_y),
                        fontsize=6, color=color, ha="right",
                        xytext=(-5, 10), textcoords="offset points",
                        fontweight="bold", alpha=0.7,
                        bbox=dict(boxstyle="round,pad=0.2", fc=ANNOT_BG, ec=color, alpha=0.5),
                    )

    # -- Probability forecast bar at right edge ----------------------
    def _enh_probability_bar(self, x: np.ndarray, df: pd.DataFrame, forecast) -> None:
        ax = self.ax_price
        if forecast is None:
            return

        # Draw small probability indicator at top-right of price chart
        prob_up = forecast.prob_up
        prob_down = forecast.prob_down

        bbox_kw = dict(boxstyle="round,pad=0.3", fc=ANNOT_BG, alpha=0.8)

        # Probability text
        if prob_up > 0.55:
            prob_color = ENH_PROB_UP
            arrow = "▲"
        elif prob_down > 0.55:
            prob_color = ENH_PROB_DN
            arrow = "▼"
        else:
            prob_color = YELLOW
            arrow = "◆"

        prob_text = (
            f"{arrow} Prob:  ↑{prob_up * 100:.0f}%  ↓{prob_down * 100:.0f}%\n"
            f"    E[move]: {forecast.expected_move_pct:+.3f}%\n"
            f"    Vol: {forecast.volatility_pct:.2f}%"
        )

        ax.annotate(
            prob_text,
            xy=(0.98, 0.97), xycoords="axes fraction",
            fontsize=7, color=prob_color, ha="right", va="top",
            fontweight="bold",
            bbox={**bbox_kw, "ec": prob_color},
            fontfamily="monospace",
        )

        # S/R levels from forecast
        if forecast.support > 0:
            ax.axhline(forecast.support, color=ENH_PROB_UP, linewidth=0.5, linestyle=":", alpha=0.3)
        if forecast.resistance > 0:
            ax.axhline(forecast.resistance, color=ENH_PROB_DN, linewidth=0.5, linestyle=":", alpha=0.3)

    # -- Psychological sentiment bar ---------------------------------
    def _enh_psych_bar(self, x: np.ndarray, df: pd.DataFrame, psych) -> None:
        ax = self.ax_vol  # Place psych info on volume panel
        if psych is None:
            return

        # Compact sentiment readout
        items = []
        if psych.fomo_level > 0.4:
            items.append(f"FOMO:{psych.fomo_level:.0%}")
        if psych.fear_level > 0.4:
            items.append(f"Fear:{psych.fear_level:.0%}")
        if psych.greed_level > 0.5:
            items.append(f"Greed:{psych.greed_level:.0%}")
        if psych.exhaustion > 0.5:
            items.append(f"Exh:{psych.exhaustion:.0%}")
        if abs(psych.accumulation) > 0.3:
            tag = "Acc" if psych.accumulation > 0 else "Dist"
            items.append(f"{tag}:{abs(psych.accumulation):.0%}")

        if not items:
            items.append("Sentiment: neutral")

        text = "  |  ".join(items)
        color = YELLOW if psych.fomo_level > 0.5 or psych.fear_level > 0.5 else TEXT

        ax.annotate(
            f"🧠 {text}",
            xy=(0.02, 0.90), xycoords="axes fraction",
            fontsize=6, color=color, ha="left", va="top",
            bbox=dict(boxstyle="round,pad=0.2", fc=ANNOT_BG, ec=color, alpha=0.6),
        )

    # ==================================================================
    # Signal History Markers
    # ==================================================================
    def _draw_signal_markers_on_price(self, x: np.ndarray, df: pd.DataFrame) -> None:
        """Draw ▲ / ▼ markers on the price chart at historical signal points."""
        if not self._signal_markers:
            return

        dates = pd.to_datetime(df["timestamp"]) if "timestamp" in df.columns else df.index
        x_dates = mdates.date2num(dates)

        for m in self._signal_markers:
            try:
                ts = pd.Timestamp(m["timestamp"])
                mx = mdates.date2num(ts)
                price = m["price"]
                sig = m["signal"]

                # Only draw if within chart x-range
                if mx < x_dates[0] or mx > x_dates[-1]:
                    continue

                if sig in (Signal.STRONG_BUY, Signal.BUY):
                    self.ax_price.annotate(
                        "▲", xy=(mx, price), fontsize=10,
                        color=BULL, ha="center", va="top",
                        fontweight="bold", alpha=0.8,
                    )
                elif sig in (Signal.STRONG_SELL, Signal.SELL):
                    self.ax_price.annotate(
                        "▼", xy=(mx, price), fontsize=10,
                        color=BEAR, ha="center", va="bottom",
                        fontweight="bold", alpha=0.8,
                    )
            except Exception:
                continue

    # ==================================================================
    # Active Trade Overlay
    # ==================================================================
    def _draw_trade_overlay(self, x: np.ndarray, df: pd.DataFrame) -> None:
        """Draw entry-price line, TP line, and P&L shading for the active trade."""
        trade = self._active_trade
        if trade is None:
            return

        ax = self.ax_price
        entry = float(trade.get("entry_price", 0))
        mark = float(trade.get("mark_price", entry))
        tp = trade.get("tp")
        sl = trade.get("sl")
        side = trade.get("side", "Buy")
        upnl = float(trade.get("unrealised_pnl", 0))

        if entry <= 0:
            return

        # Determine P&L colour
        pnl_color = BULL if upnl >= 0 else BEAR

        # ---- Entry price line (dashed white) ----
        ax.axhline(entry, color="#ffffff", linewidth=1.0, linestyle="--", alpha=0.7, zorder=5)
        label_side = "Buy" if side in ("Buy", "LONG") else "Sell"
        ax.annotate(
            f"  ENTRY {label_side} {entry:,.4f}",
            xy=(x[-1], entry),
            fontsize=7, color="#ffffff", fontweight="bold", va="bottom",
            xytext=(6, 2), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.2", fc="#0d1117", ec="#ffffff", alpha=0.75),
            zorder=6,
        )

        # ---- TP line (dotted green) ----
        if tp is not None and float(tp) > 0:
            tp_f = float(tp)
            ax.axhline(tp_f, color=BULL, linewidth=0.9, linestyle=":", alpha=0.65, zorder=5)
            ax.annotate(
                f"  TP {tp_f:,.4f}",
                xy=(x[-1], tp_f),
                fontsize=7, color=BULL, fontweight="bold", va="bottom",
                xytext=(6, 2), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.2", fc="#0d1117", ec=BULL, alpha=0.75),
                zorder=6,
            )

        # ---- SL line (dotted red) ----
        if sl is not None and float(sl) > 0:
            sl_f = float(sl)
            ax.axhline(sl_f, color=BEAR, linewidth=0.9, linestyle=":", alpha=0.65, zorder=5)
            ax.annotate(
                f"  SL {sl_f:,.4f}",
                xy=(x[-1], sl_f),
                fontsize=7, color=BEAR, fontweight="bold", va="top",
                xytext=(6, -2), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.2", fc="#0d1117", ec=BEAR, alpha=0.75),
                zorder=6,
            )

        # ---- P&L shaded band between entry and mark ----
        low, high = min(entry, mark), max(entry, mark)
        if abs(high - low) > 0:
            ax.axhspan(low, high, alpha=0.10, color=pnl_color, zorder=1)

        # ---- P&L annotation (right side) ----
        pnl_pct = upnl / (entry * float(trade.get("size", 1))) * 100 if entry > 0 and float(trade.get("size", 1)) > 0 else 0
        ax.annotate(
            f" P&L: ${upnl:+,.2f} ({pnl_pct:+.2f}%)",
            xy=(x[-1], mark),
            fontsize=8, color=pnl_color, fontweight="bold", va="center",
            xytext=(6, 0), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.25", fc="#0d1117", ec=pnl_color, alpha=0.85),
            zorder=7,
        )
