"""
CryptoPenetratorXL — Bybit WebSocket Client

Streams real-time kline, ticker, and orderbook data.
Runs in a background thread and pushes events via callbacks.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

from pybit.unified_trading import WebSocket

from app.core.config import get_settings
from app.core.logger import get_logger

log = get_logger("api.ws")


class BybitWebSocket:
    """Manages a persistent WebSocket connection for live data feeds."""

    def __init__(self) -> None:
        cfg = get_settings()
        self._api_key = cfg.bybit_api_key
        self._api_secret = cfg.bybit_secret_key
        self._testnet = cfg.bybit_testnet
        self._ws: WebSocket | None = None
        self._callbacks: dict[str, list[Callable]] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Open the WebSocket connection in a background thread."""
        if self._running:
            return
        self._running = True
        self._ws = WebSocket(
            testnet=self._testnet,
            channel_type="linear",
        )
        log.info("WebSocket connected")

    def stop(self) -> None:
        """Gracefully close the WebSocket connection."""
        self._running = False
        if self._ws:
            try:
                self._ws.exit()
            except Exception:
                pass
            self._ws = None
        log.info("WebSocket disconnected")

    def subscribe_kline(
        self, symbol: str, interval: str, callback: Callable[[dict], None],
    ) -> None:
        """Subscribe to kline (candlestick) stream."""
        if not self._ws:
            self.start()
        topic = f"kline.{interval}.{symbol}"
        self._ws.kline_stream(interval=interval, symbol=symbol, callback=callback)  # type: ignore
        log.info("Subscribed to %s", topic)

    def subscribe_ticker(
        self, symbol: str, callback: Callable[[dict], None],
    ) -> None:
        """Subscribe to ticker stream."""
        if not self._ws:
            self.start()
        self._ws.ticker_stream(symbol=symbol, callback=callback)  # type: ignore
        log.info("Subscribed to ticker.%s", symbol)

    def subscribe_orderbook(
        self, symbol: str, depth: int, callback: Callable[[dict], None],
    ) -> None:
        """Subscribe to order-book stream."""
        if not self._ws:
            self.start()
        self._ws.orderbook_stream(depth=depth, symbol=symbol, callback=callback)  # type: ignore
        log.info("Subscribed to orderbook.%s.%s", depth, symbol)

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._running
