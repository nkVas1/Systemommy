"""
CryptoPenetratorXL — Core Configuration

Loads settings from .env and provides a cached singleton.
No Redis, no Postgres — fully portable with SQLite.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
MODELS_DIR = DATA_DIR / "models"
DB_PATH = DATA_DIR / "crypto_pen.db"

for _d in (DATA_DIR, LOGS_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    """Application-wide settings loaded from .env (auto-detected)."""

    # -- Environment ---------------------------------------------------------
    environment: str = Field("development", alias="ENVIRONMENT")
    debug: bool = Field(False, alias="DEBUG")
    trading_mode: str = Field("paper", alias="TRADING_MODE")  # paper | live

    # -- Bybit ---------------------------------------------------------------
    bybit_api_key: str = Field("", alias="BYBIT_API_KEY")
    bybit_secret_key: str = Field("", alias="BYBIT_SECRET_KEY")
    bybit_testnet: bool = Field(False, alias="BYBIT_TESTNET")

    # -- Trading defaults ----------------------------------------------------
    default_leverage: float = Field(2.0, alias="DEFAULT_LEVERAGE")
    max_leverage: float = Field(2.0, alias="MAX_LEVERAGE")
    default_symbols: list[str] = Field(
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
        alias="DEFAULT_SYMBOLS",
    )
    default_timeframe: str = Field("15", alias="DEFAULT_TIMEFRAME")  # minutes

    # -- Position & risk -----------------------------------------------------
    # Full-balance strategy: always trade 100% of available equity
    use_full_balance: bool = Field(True, alias="USE_FULL_BALANCE")
    max_open_positions: int = Field(1, alias="MAX_OPEN_POSITIONS")

    # Stop loss: disabled by default (user never uses SL)
    use_stop_loss: bool = Field(False, alias="USE_STOP_LOSS")
    stop_loss_pct: float = Field(0.0, alias="STOP_LOSS_PCT")

    # Take profit target: 0.3 – 0.6% net profit per trade
    take_profit_pct: float = Field(0.005, alias="TAKE_PROFIT_PCT")     # 0.5% (середина диапазона)
    tp_min_pct: float = Field(0.003, alias="TP_MIN_PCT")               # 0.3% минимум
    tp_max_pct: float = Field(0.006, alias="TP_MAX_PCT")               # 0.6% максимум

    # Bybit maker fee (one side) — used for net-profit calculations
    # Using limit orders to benefit from lower maker fees (0.02%)
    exchange_fee_pct: float = Field(0.0002, alias="EXCHANGE_FEE_PCT")  # 0.02%

    # -- Indicator params (your personal set) --------------------------------
    stoch_k: int = Field(14, alias="STOCH_K")
    stoch_d: int = Field(3, alias="STOCH_D")
    stoch_smooth: int = Field(1, alias="STOCH_SMOOTH")  # %K slowing
    macd_fast: int = Field(12, alias="MACD_FAST")
    macd_slow: int = Field(26, alias="MACD_SLOW")
    macd_signal: int = Field(9, alias="MACD_SIGNAL")
    cci_period: int = Field(20, alias="CCI_PERIOD")

    # -- Monitoring ----------------------------------------------------------
    monitor_interval_sec: int = Field(60, alias="MONITOR_INTERVAL_SEC")  # seconds

    # -- Logging -------------------------------------------------------------
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # -- Database ------------------------------------------------------------
    db_url: str = Field(
        f"sqlite+aiosqlite:///{DB_PATH}",
        alias="DB_URL",
    )

    # -- Validators ----------------------------------------------------------
    @field_validator("trading_mode")
    @classmethod
    def validate_trading_mode(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("paper", "live"):
            raise ValueError("TRADING_MODE must be 'paper' or 'live'")
        return v

    @field_validator("default_symbols", mode="before")
    @classmethod
    def parse_symbols(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [s.strip().upper() for s in v.split(",") if s.strip()]
        return v

    model_config = {
        "env_file": str(BASE_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton for app settings."""
    return Settings()
