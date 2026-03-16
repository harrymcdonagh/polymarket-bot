import pytest
from unittest.mock import MagicMock, patch
from src.research.clob import CLOBSource

@pytest.fixture
def clob():
    return CLOBSource()

def test_clob_is_available(clob):
    assert clob.is_available() is True

def test_clob_name(clob):
    assert clob.name == "clob"

@pytest.mark.asyncio
async def test_clob_fetch_returns_features(clob):
    market = MagicMock()
    market.token_yes_id = "token-123"
    market.yes_price = 0.60
    mock_book = {
        "bids": [{"price": "0.58", "size": "100"}, {"price": "0.57", "size": "200"}, {"price": "0.56", "size": "150"}],
        "asks": [{"price": "0.62", "size": "80"}, {"price": "0.63", "size": "120"}, {"price": "0.64", "size": "100"}],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_book
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await clob.fetch(market)
    assert "clob_bid_ask_spread" in result
    assert "clob_buy_depth" in result
    assert "clob_sell_depth" in result
    assert "clob_imbalance" in result
    assert "clob_midpoint_vs_gamma" in result
    assert len(result) == 5
    assert result["clob_bid_ask_spread"] == pytest.approx(0.04)

@pytest.mark.asyncio
async def test_clob_fetch_empty_on_error(clob):
    market = MagicMock()
    market.token_yes_id = "token-123"
    market.yes_price = 0.60
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.json.side_effect = Exception("Server error")
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await clob.fetch(market)
    assert result == {}
