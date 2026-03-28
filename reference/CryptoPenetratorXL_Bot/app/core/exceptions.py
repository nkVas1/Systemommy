"""
CryptoPenetratorXL — Custom Exceptions
"""


class CryptoPenError(Exception):
    """Base exception for CryptoPenetratorXL."""


class APIError(CryptoPenError):
    """Bybit API communication error."""


class InsufficientBalanceError(CryptoPenError):
    """Not enough balance to open a position."""


class RiskLimitExceeded(CryptoPenError):
    """Risk management rule violated."""


class InvalidSymbolError(CryptoPenError):
    """Unknown or unsupported trading pair."""


class ConfigurationError(CryptoPenError):
    """Invalid configuration."""


class DataError(CryptoPenError):
    """Data acquisition or processing error."""


class OrderExecutionError(CryptoPenError):
    """Failed to place / cancel / modify an order."""
