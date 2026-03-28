"""
CryptoPenetratorXL — Utility Helpers
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


def fmt_price(price: float, precision: int = 2, tick_size: float = 0.0) -> str:
    """Format a price with adaptive precision.

    When *tick_size* is supplied (e.g. 0.0001 for XRPUSDT), the precision is
    derived from the tick size so the displayed price reflects the actual
    tradable resolution.  Otherwise falls back to *precision* for prices >= 1,
    or an adaptive scheme for sub-dollar prices.
    """
    if tick_size > 0:
        tick_precision = max(0, -int(math.floor(math.log10(tick_size))))
        return f"{price:,.{tick_precision}f}"
    if price >= 1:
        return f"{price:,.{precision}f}"
    # For sub-dollar prices, show more decimals
    if price == 0:
        return "0.00"
    significant = max(2, -int(math.floor(math.log10(abs(price)))) + 2)
    return f"{price:.{significant}f}"


def fmt_pct(value: float) -> str:
    """Format as percentage string with sign."""
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def fmt_qty(qty: float) -> str:
    """Format quantity with adaptive precision."""
    if qty >= 100:
        return f"{qty:,.2f}"
    elif qty >= 1:
        return f"{qty:.4f}"
    else:
        return f"{qty:.6f}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ts_to_str(ts: datetime | None) -> str:
    if ts is None:
        return "—"
    return ts.strftime("%Y-%m-%d %H:%M:%S")
