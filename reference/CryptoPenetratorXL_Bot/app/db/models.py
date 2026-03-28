"""
CryptoPenetratorXL — SQLAlchemy Models (SQLite)

Trade history, signals, and settings persisted locally.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import DB_PATH


class Base(DeclarativeBase):
    pass


class TradeRecord(Base):
    """Persisted trade (both paper and live)."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # Buy / Sell
    qty = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    leverage = Column(Float, default=1.0)
    pnl = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    status = Column(String(16), default="OPEN")  # OPEN / CLOSED / CANCELLED
    mode = Column(String(10), default="paper")   # paper / live
    confidence = Column(Float, nullable=True)
    risk_reward = Column(Float, nullable=True)
    signal_type = Column(String(20), nullable=True)
    timeframe = Column(String(10), nullable=True)
    opened_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)


class SignalRecord(Base):
    """Persisted signal for analysis / backtesting."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    signal = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=False)
    confluence_score = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    indicator_json = Column(Text, nullable=True)
    candle_pattern = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def set_indicators(self, data: dict) -> None:
        self.indicator_json = json.dumps(data)

    def get_indicators(self) -> dict:
        return json.loads(self.indicator_json) if self.indicator_json else {}


class AppSetting(Base):
    """Key-value settings store."""
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
