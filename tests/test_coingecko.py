import pytest
from unittest.mock import MagicMock, patch
from src.research.coingecko import CoinGeckoSource

@pytest.fixture
def cg():
    return CoinGeckoSource()

def test_coingecko_is_available(cg):
    assert cg.is_available() is True

def test_coingecko_name(cg):
    assert cg.name == "coingecko"

@pytest.mark.asyncio
async def test_coingecko_crypto_market(cg):
    market = MagicMock()
    market.question = "Will Bitcoin exceed $100k by end of 2026?"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"bitcoin": {"usd": 95000, "usd_24h_change": 2.5, "usd_market_cap": 1800000000000}}
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await cg.fetch(market)
    assert result["crypto_is_relevant"] == 1.0
    assert result["crypto_price_usd"] == 95000
    assert result["crypto_24h_change"] == 2.5
    assert result["crypto_market_cap"] == 1800000000000

@pytest.mark.asyncio
async def test_coingecko_non_crypto_market(cg):
    market = MagicMock()
    market.question = "Will the US enter a recession in 2026?"
    result = await cg.fetch(market)
    assert result["crypto_is_relevant"] == 0.0
    assert result["crypto_price_usd"] == 0.0

@pytest.mark.asyncio
async def test_coingecko_api_error(cg):
    market = MagicMock()
    market.question = "Will Bitcoin hit $200k?"
    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        result = await cg.fetch(market)
    assert result == {}
