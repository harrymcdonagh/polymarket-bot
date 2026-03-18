import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import pandas as pd
from src.data_feed import CryptoDataFeed


@pytest.fixture
def feed():
    return CryptoDataFeed()


def test_feed_default_exchange(feed):
    assert feed.exchange_id == "coinbase"


def _make_ohlcv_data(count=5):
    import time
    base = int(time.time() * 1000) - count * 60000
    return [[base + i * 60000, 84000 + i, 84100 + i, 83900 + i, 84050 + i, 100 + i]
            for i in range(count)]


async def test_fetch_candles_returns_dataframe(feed):
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=_make_ohlcv_data(10))
    with patch.object(feed, '_get_exchange', return_value=mock_exchange):
        df = await feed.fetch_candles("BTC/USDT", limit=10, min_candles=5)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 10
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


async def test_fetch_candles_minimum_threshold(feed):
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=_make_ohlcv_data(5))
    with patch.object(feed, '_get_exchange', return_value=mock_exchange):
        df = await feed.fetch_candles("BTC/USDT", limit=100, min_candles=60)
    assert df is None


async def test_fetch_candles_error_returns_none(feed):
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(side_effect=Exception("API error"))
    with patch.object(feed, '_get_exchange', return_value=mock_exchange):
        df = await feed.fetch_candles("BTC/USDT", limit=10)
    assert df is None
