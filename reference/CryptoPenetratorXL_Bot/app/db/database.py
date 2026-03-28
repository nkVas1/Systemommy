"""
CryptoPenetratorXL — Database Manager (SQLite, synchronous)

Provides session management, table creation, and CRUD helpers.
Uses sync SQLAlchemy with SQLite — no external DB server required.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DB_PATH
from app.core.logger import get_logger
from app.db.models import AppSetting, Base, SignalRecord, TradeRecord

log = get_logger("db")

_DB_URL = f"sqlite:///{DB_PATH}"
_engine = create_engine(_DB_URL, echo=False, future=True)
_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(_engine)
    log.info("Database initialised at %s", DB_PATH)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context-managed session with auto commit / rollback."""
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Trade CRUD
# ---------------------------------------------------------------------------
def save_trade(data: dict[str, Any]) -> TradeRecord:
    """Persist a trade result dict."""
    with get_session() as s:
        rec = TradeRecord(
            order_id=data.get("order_id", ""),
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            qty=data.get("qty", 0),
            entry_price=data.get("entry_price", 0),
            stop_loss=data.get("stop_loss"),
            take_profit=data.get("take_profit"),
            leverage=data.get("leverage", 1),
            status="OPEN",
            mode=data.get("mode", "paper"),
            confidence=data.get("confidence"),
            risk_reward=data.get("risk_reward"),
            signal_type=data.get("signal_type"),
            timeframe=data.get("timeframe"),
            notes=data.get("notes"),
        )
        s.add(rec)
        s.flush()
        log.info("Trade saved: %s %s %s id=%s", rec.side, rec.symbol, rec.mode, rec.order_id)
        return rec


def close_trade(order_id: str, exit_price: float, pnl: float, pnl_pct: float) -> None:
    """Mark a trade as CLOSED."""
    with get_session() as s:
        rec = s.query(TradeRecord).filter_by(order_id=order_id).first()
        if rec:
            rec.exit_price = exit_price
            rec.pnl = pnl
            rec.pnl_pct = pnl_pct
            rec.status = "CLOSED"
            rec.closed_at = datetime.now(timezone.utc)
            log.info("Trade closed: %s pnl=%.2f (%.2f%%)", order_id, pnl, pnl_pct)


def get_open_trades() -> list[TradeRecord]:
    with get_session() as s:
        return s.query(TradeRecord).filter_by(status="OPEN").all()


def get_trade_history(limit: int = 100, mode: str | None = None) -> list[TradeRecord]:
    """Return trade history, optionally filtered by trading mode ('paper' or 'live')."""
    with get_session() as s:
        q = s.query(TradeRecord)
        if mode:
            q = q.filter_by(mode=mode)
        return q.order_by(TradeRecord.opened_at.desc()).limit(limit).all()


# ---------------------------------------------------------------------------
# Signal CRUD
# ---------------------------------------------------------------------------
def save_signal(data: dict[str, Any]) -> SignalRecord:
    """Persist a signal analysis."""
    with get_session() as s:
        rec = SignalRecord(
            symbol=data.get("symbol", ""),
            timeframe=data.get("timeframe", ""),
            signal=data.get("signal", "HOLD"),
            confidence=data.get("confidence", 0),
            confluence_score=data.get("confluence_score"),
            entry_price=data.get("entry_price"),
            stop_loss=data.get("stop_loss"),
            take_profit=data.get("take_profit"),
            indicator_json=json.dumps(data.get("indicator_detail", {})),
            candle_pattern=data.get("candle_pattern"),
        )
        s.add(rec)
        return rec


def get_recent_signals(symbol: str | None = None, limit: int = 50) -> list[SignalRecord]:
    with get_session() as s:
        q = s.query(SignalRecord)
        if symbol:
            q = q.filter_by(symbol=symbol)
        return q.order_by(SignalRecord.created_at.desc()).limit(limit).all()


# ---------------------------------------------------------------------------
# App settings
# ---------------------------------------------------------------------------
def get_setting(key: str, default: str | None = None) -> str | None:
    with get_session() as s:
        rec = s.query(AppSetting).filter_by(key=key).first()
        return rec.value if rec else default


def set_setting(key: str, value: str) -> None:
    with get_session() as s:
        rec = s.query(AppSetting).filter_by(key=key).first()
        if rec:
            rec.value = value
            rec.updated_at = datetime.now(timezone.utc)
        else:
            s.add(AppSetting(key=key, value=value))


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------
def get_trade_stats(mode: str | None = None) -> dict[str, Any]:
    """Return summary statistics of closed trades, optionally filtered by mode."""
    with get_session() as s:
        q = s.query(TradeRecord).filter_by(status="CLOSED")
        if mode:
            q = q.filter_by(mode=mode)
        closed = q.all()
        if not closed:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0, "avg_pnl": 0}

        wins = [t for t in closed if (t.pnl or 0) > 0]
        losses = [t for t in closed if (t.pnl or 0) <= 0]
        total_pnl = sum(t.pnl or 0 for t in closed)
        return {
            "total": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / len(closed), 2),
        }
