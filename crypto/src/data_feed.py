import logging
import pandas as pd

logger = logging.getLogger(__name__)


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
        try:
            exchange = self._get_exchange()
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if len(ohlcv) < min_candles:
                logger.warning(f"Insufficient candles: got {len(ohlcv)}, need {min_candles}")
                return None
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            return df
        except Exception as e:
            logger.error(f"Failed to fetch candles: {e}")
            return None

    async def close(self):
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None
