"""
CryptoPenetratorXL — Trading Constants
"""

from enum import Enum


class Side(str, Enum):
    LONG = "Buy"
    SHORT = "Sell"


class Signal(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class OrderType(str, Enum):
    MARKET = "Market"
    LIMIT = "Limit"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Timeframe(str, Enum):
    """Bybit kline intervals (value = API string)."""
    M1 = "1"
    M3 = "3"
    M5 = "5"
    M15 = "15"
    M30 = "30"
    H1 = "60"
    H4 = "240"
    D1 = "D"
    W1 = "W"

    @property
    def label(self) -> str:
        _map = {
            "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m",
            "60": "1h", "240": "4h", "D": "1D", "W": "1W",
        }
        return _map[self.value]


# Confluence thresholds  (tuned for intraday scalping)
CONFLUENCE_STRONG = 0.45   # ≥45% weighted agreement → strong signal
CONFLUENCE_NORMAL = 0.20   # ≥20% weighted agreement → normal signal

# Stochastic zones
STOCH_OVERSOLD = 20
STOCH_OVERBOUGHT = 80

# CCI zones
CCI_OVERSOLD = -100
CCI_OVERBOUGHT = 100

# MACD signal thresholds (histogram)
MACD_HIST_THRESHOLD = 0.0

# Volume spike multiplier
VOLUME_SPIKE_MULT = 1.5
