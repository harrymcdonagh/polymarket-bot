import asyncio
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Coinbase returns max ~300 candles per request
_BATCH_SIZE = 300


class CryptoDataFeed:
    def __init__(self, exchange_id: str = "coinbase"):
        self.exchange_id = exchange_id
        self._exchange = None

    def _get_exchange(self):
        if self._exchange is None:
            import ccxt.async_support as ccxt
            exchange_class = getattr(ccxt, self.exchange_id)
            self._exchange = exchange_class({"enableRateLimit": True})
        return self._exchange

    async def fetch_candles(self, symbol: str = "BTC/USDT", timeframe: str = "1m",
                            limit: int = 100, min_candles: int = 60) -> pd.DataFrame | None:
        """Fetch candles. If limit > 300, paginates backward in batches."""
        try:
            exchange = self._get_exchange()
            if limit <= _BATCH_SIZE:
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            else:
                ohlcv = await self._fetch_paginated(exchange, symbol, timeframe, limit)

            if len(ohlcv) < min_candles:
                logger.warning(f"Insufficient candles: got {len(ohlcv)}, need {min_candles}")
                return None
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
            logger.info(f"Fetched {len(df)} candles for {symbol}")
            return df
        except Exception as e:
            logger.error(f"Failed to fetch candles: {e}")
            return None

    async def _fetch_paginated(self, exchange, symbol: str, timeframe: str, limit: int) -> list:
        """Fetch `limit` candles by paginating backward from now."""
        all_ohlcv = []
        # Start from the most recent batch
        latest = await exchange.fetch_ohlcv(symbol, timeframe, limit=_BATCH_SIZE)
        if not latest:
            return all_ohlcv
        all_ohlcv = latest
        remaining = limit - len(latest)

        while remaining > 0 and all_ohlcv:
            # Fetch the batch ending just before our earliest candle
            earliest_ts = all_ohlcv[0][0]
            batch_size = min(_BATCH_SIZE, remaining)
            # since = earliest - batch_size * 60000 (1m candles)
            since = earliest_ts - batch_size * 60000
            batch = await exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=batch_size)
            if not batch:
                break
            # Filter out any overlap
            batch = [c for c in batch if c[0] < earliest_ts]
            if not batch:
                break
            all_ohlcv = batch + all_ohlcv
            remaining -= len(batch)
            logger.info(f"Paginating: {len(all_ohlcv)}/{limit} candles fetched")
            await asyncio.sleep(0.2)  # rate limit

        return all_ohlcv[:limit]

    async def close(self):
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None
