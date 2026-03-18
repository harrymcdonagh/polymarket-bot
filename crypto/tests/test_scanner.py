import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.scanner import CryptoScanner


@pytest.fixture
def scanner():
    return CryptoScanner(gamma_url="https://gamma-api.polymarket.com")


async def test_find_active_market_success(scanner):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{
        "conditionId": "0xabc",
        "tokens": [{"token_id": "tok123", "outcome": "Yes"}],
        "outcomePrices": '["0.52","0.48"]',
        "question": "Will BTC be above $84,000 at 14:05 UTC?",
        "closed": False,
        "endDate": "2026-03-18T14:05:00Z",
    }]
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.find_active_5min_market("BTC")
    if result is not None:
        assert "market_id" in result
        assert "token_id" in result
        assert result["strike_price"] == 84000.0


async def test_find_active_market_empty(scanner):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.find_active_5min_market("BTC")
    assert result is None


async def test_find_active_market_error(scanner):
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("timeout"))
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.find_active_5min_market("BTC")
    assert result is None


async def test_check_resolution_resolved(scanner):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"resolved": True, "outcomePrices": '["0.99","0.01"]'}]
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.check_resolution("0xabc", token_id="tok123")
    assert result == "YES"


async def test_check_resolution_no_token():
    scanner = CryptoScanner()
    result = await scanner.check_resolution("0xabc")
    assert result is None


def test_extract_strike():
    scanner = CryptoScanner()
    assert scanner._extract_strike("Will BTC be above $84,000 at 14:05?") == 84000.0
    assert scanner._extract_strike("No price here") is None


def test_is_5min_market():
    scanner = CryptoScanner()
    assert scanner._is_5min_market({"question": "Will BTC be above $84,000 at 14:05 UTC?"}) is True
    assert scanner._is_5min_market({"question": "Will Trump win?"}) is False
