"""
CryptoPenetratorXL — Bybit REST API Client

Unified Trading Account V5 wrapper.  Handles klines, account, orders,
positions with retries and structured logging.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
from pybit.unified_trading import HTTP
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.constants import OrderType, Side, Timeframe
from app.core.exceptions import APIError, OrderExecutionError
from app.core.logger import get_logger, log_perf

log = get_logger("api.bybit")


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert to float, returning *default* for empty/None values."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class BybitClient:
    """Thin, retry-resilient wrapper around pybit HTTP for Unified Trading V5."""

    def __init__(self) -> None:
        cfg = get_settings()
        # Paper mode ALWAYS uses mainnet for real market data
        use_testnet = cfg.bybit_testnet and cfg.trading_mode == "live"
        if cfg.bybit_testnet and cfg.trading_mode != "live":
            log.info("Paper mode — testnet flag ignored, using mainnet (real prices)")
        self._client = HTTP(
            api_key=cfg.bybit_api_key,
            api_secret=cfg.bybit_secret_key,
            testnet=use_testnet,
        )
        self.session = self._client      # alias used by LatencyWorker
        self._instrument_cache: dict[str, list[dict]] = {}  # symbol → instrument info
        log.info("BybitClient initialised  [testnet=%s, mode=%s]", use_testnet, cfg.trading_mode)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_klines(
        self,
        symbol: str,
        interval: str = "15",
        limit: int = 200,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles. Returns DataFrame indexed by datetime."""
        log.debug("get_klines  symbol=%s  interval=%s  limit=%d", symbol, interval, limit)
        with log_perf(log, f"get_klines({symbol}, {interval})"):
            resp = self._client.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
            self._check(resp)
        rows = resp["result"]["list"]
        df = pd.DataFrame(
            rows,
            columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"],
        )
        for col in ("open", "high", "low", "close", "volume", "turnover"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
        df.sort_values("timestamp", inplace=True)
        df.set_index("timestamp", inplace=True)
        df.reset_index(inplace=True)
        log.debug("get_klines  → %d rows  [%s … %s]",
                  len(df),
                  df["timestamp"].iloc[0] if len(df) else "?",
                  df["timestamp"].iloc[-1] if len(df) else "?")
        return df

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_ticker(self, symbol: str) -> dict[str, Any]:
        """Return real-time ticker for *symbol*."""
        log.debug("get_ticker  symbol=%s", symbol)
        with log_perf(log, f"get_ticker({symbol})"):
            resp = self._client.get_tickers(category="linear", symbol=symbol)
            self._check(resp)
        items = resp["result"]["list"]
        if not items:
            raise APIError(f"No ticker found for {symbol}")
        log.debug("get_ticker  → lastPrice=%s", items[0].get("lastPrice"))
        return items[0]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_tickers(self) -> list[dict[str, Any]]:
        """Return tickers for all linear perpetual contracts."""
        log.debug("get_tickers  (all linear)")
        with log_perf(log, "get_tickers(all)"):
            resp = self._client.get_tickers(category="linear")
            self._check(resp)
        tickers = resp["result"]["list"]
        log.debug("get_tickers  → %d instruments", len(tickers))
        return tickers

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_orderbook(self, symbol: str, limit: int = 25) -> dict:
        """Return L2 order-book snapshot."""
        log.debug("get_orderbook  symbol=%s  limit=%d", symbol, limit)
        with log_perf(log, f"get_orderbook({symbol})"):
            resp = self._client.get_orderbook(category="linear", symbol=symbol, limit=limit)
            self._check(resp)
        return resp["result"]

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_wallet_balance(self, coin: str = "USDT") -> dict[str, Any]:
        """Return unified account wallet balance.  Falls back to CONTRACT if UNIFIED fails."""
        log.debug("get_wallet_balance  coin=%s", coin)
        for acct_type in ("UNIFIED", "CONTRACT"):
            try:
                with log_perf(log, f"get_wallet_balance({acct_type})"):
                    resp = self._client.get_wallet_balance(accountType=acct_type, coin=coin)
                    self._check(resp)
                accounts = resp["result"]["list"]
                if not accounts:
                    log.debug("get_wallet_balance  %s → empty accounts", acct_type)
                    continue
                for acct in accounts:
                    for c in acct.get("coin", []):
                        if c["coin"] == coin:
                            # availableToOrder reflects actual tradable funds
                            # (fallback chain: availableToOrder → availableToWithdraw → walletBalance)
                            available = _safe_float(c.get("availableToOrder", 0))
                            if available <= 0:
                                available = _safe_float(c.get("availableToWithdraw", 0))
                            if available <= 0:
                                available = _safe_float(c.get("walletBalance", 0))
                            result = {
                                "equity": _safe_float(c.get("equity", 0)),
                                "available": available,
                                "wallet_balance": _safe_float(c.get("walletBalance", 0)),
                                "unrealised_pnl": _safe_float(c.get("unrealisedPnl", 0)),
                            }
                            log.debug(
                                "get_wallet_balance  → equity=$%.2f  available=$%.2f  "
                                "uPnL=$%.2f  [%s]",
                                result["equity"], result["available"],
                                result["unrealised_pnl"], acct_type,
                            )
                            return result
            except Exception as exc:
                log.debug("get_wallet_balance  %s failed: %s", acct_type, exc)
                continue  # try next account type
        raise APIError(f"Wallet balance unavailable (tried UNIFIED + CONTRACT)")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return open positions.  If *symbol* is None, returns all."""
        log.debug("get_positions  symbol=%s", symbol or "ALL")
        params: dict[str, Any] = {"category": "linear", "settleCoin": "USDT"}
        if symbol:
            params["symbol"] = symbol
        with log_perf(log, f"get_positions({symbol or 'ALL'})"):
            resp = self._client.get_positions(**params)
            self._check(resp)
        positions = []
        for p in resp["result"]["list"]:
            size = _safe_float(p.get("size", 0))
            if size > 0:
                positions.append({
                    "symbol": p["symbol"],
                    "side": p["side"],
                    "size": size,
                    "entry_price": _safe_float(p.get("avgPrice", 0)),
                    "mark_price": _safe_float(p.get("markPrice", 0)),
                    "unrealised_pnl": _safe_float(p.get("unrealisedPnl", 0)),
                    "leverage": p.get("leverage", "1"),
                    "liq_price": _safe_float(p.get("liqPrice")) if p.get("liqPrice") else None,
                    "tp": p.get("takeProfit"),
                    "sl": p.get("stopLoss"),
                })
        log.debug("get_positions  → %d open position(s)", len(positions))
        for pos in positions:
            log.debug(
                "  position: %s %s  size=%.6f  entry=%.4f  uPnL=%.2f  lev=%s",
                pos["side"], pos["symbol"], pos["size"],
                pos["entry_price"], pos["unrealised_pnl"], pos["leverage"],
            )
        return positions

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    def set_leverage(self, symbol: str, leverage: float) -> None:
        """Set leverage for a symbol (idempotent — ignores 'leverage not modified')."""
        log.debug("set_leverage  symbol=%s  leverage=%.1f", symbol, leverage)
        try:
            resp = self._client.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
            if resp.get("retCode", 0) not in (0, 110043):
                raise APIError(f"set_leverage failed: {resp}")
            log.debug("set_leverage  → OK")
        except Exception as e:
            if "leverage not modified" in str(e).lower() or "110043" in str(e):
                log.debug("set_leverage  already set to %.1f — skipped", leverage)
                return  # already set
            raise

    def place_order(
        self,
        symbol: str,
        side: Side,
        qty: float,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """Place an order and return the response dict."""
        params: dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "side": side.value,
            "orderType": order_type.value,
            "qty": str(qty),
            "timeInForce": "GTC",
        }
        if order_type == OrderType.LIMIT and price is not None:
            params["price"] = str(price)
        if sl is not None:
            params["stopLoss"] = str(sl)
        if tp is not None:
            params["takeProfit"] = str(tp)
        if reduce_only:
            params["reduceOnly"] = True

        log.info(
            "Placing order: %s %s %s qty=%s sl=%s tp=%s reduce_only=%s",
            side.value, symbol, order_type.value, qty, sl, tp, reduce_only,
        )
        try:
            with log_perf(log, f"place_order({symbol})", level=logging.INFO):
                resp = self._client.place_order(**params)
                self._check(resp)
            order_id = resp["result"].get("orderId", "")
            log.info("Order placed OK  [orderId=%s]", order_id)
            return resp["result"]
        except Exception as e:
            log.error("Order FAILED: %s  params=%s", e, params)
            raise OrderExecutionError(str(e)) from e

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        """Cancel a pending order."""
        log.info("cancel_order  symbol=%s  orderId=%s", symbol, order_id)
        resp = self._client.cancel_order(
            category="linear", symbol=symbol, orderId=order_id,
        )
        self._check(resp)
        log.info("cancel_order  → OK")
        return resp["result"]

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel all open orders for a symbol."""
        log.info("cancel_all_orders  symbol=%s", symbol)
        resp = self._client.cancel_all_orders(category="linear", symbol=symbol)
        self._check(resp)
        log.info("cancel_all_orders  → OK")
        return resp["result"]

    def close_position(self, symbol: str, side: Side, qty: float) -> dict:
        """Market-close a position (reduce-only)."""
        log.info("close_position  %s %s  qty=%.6f", side.value, symbol, qty)
        close_side = Side.SHORT if side == Side.LONG else Side.LONG
        return self.place_order(
            symbol=symbol,
            side=close_side,
            qty=qty,
            order_type=OrderType.MARKET,
            reduce_only=True,
        )

    # ------------------------------------------------------------------
    # Instrument info
    # ------------------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_instruments(self, symbol: str | None = None) -> list[dict]:
        """Return instrument info (lot size, tick size, etc.).

        Results are cached per symbol to avoid redundant API calls — instrument
        specs (tick size, lot size) rarely change during a session.
        """
        if symbol and symbol in self._instrument_cache:
            return self._instrument_cache[symbol]

        log.debug("get_instruments  symbol=%s", symbol or "ALL")
        params: dict[str, Any] = {"category": "linear"}
        if symbol:
            params["symbol"] = symbol
        with log_perf(log, f"get_instruments({symbol or 'ALL'})"):
            resp = self._client.get_instruments_info(**params)
            self._check(resp)
        instruments = resp["result"]["list"]
        log.debug("get_instruments  → %d result(s)", len(instruments))

        if symbol and instruments:
            self._instrument_cache[symbol] = instruments
        return instruments

    def get_min_order_qty(self, symbol: str) -> float:
        """Return minimum order quantity for *symbol*."""
        instruments = self.get_instruments(symbol)
        if instruments:
            lot = instruments[0].get("lotSizeFilter", {})
            min_qty = float(lot.get("minOrderQty", 0.001))
            log.debug("get_min_order_qty  %s → %s", symbol, min_qty)
            return min_qty
        log.debug("get_min_order_qty  %s → default 0.001 (no instrument data)", symbol)
        return 0.001

    def get_qty_step(self, symbol: str) -> float:
        """Return qty step (precision) for *symbol*."""
        instruments = self.get_instruments(symbol)
        if instruments:
            lot = instruments[0].get("lotSizeFilter", {})
            step = float(lot.get("qtyStep", 0.001))
            log.debug("get_qty_step  %s → %s", symbol, step)
            return step
        log.debug("get_qty_step  %s → default 0.001 (no instrument data)", symbol)
        return 0.001

    def get_tick_size(self, symbol: str) -> float:
        """Return price tick size for *symbol*."""
        instruments = self.get_instruments(symbol)
        if instruments:
            price_filter = instruments[0].get("priceFilter", {})
            tick = float(price_filter.get("tickSize", 0.01))
            log.debug("get_tick_size  %s → %s", symbol, tick)
            return tick
        log.debug("get_tick_size  %s → default 0.01 (no instrument data)", symbol)
        return 0.01

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _check(resp: dict) -> None:
        code = resp.get("retCode", -1)
        if code != 0:
            msg = resp.get("retMsg", "unknown error")
            raise APIError(f"Bybit API error [{code}]: {msg}")
