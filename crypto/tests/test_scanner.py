import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.scanner import CryptoScanner


@pytest.fixture
def scanner():
    return CryptoScanner(gamma_url="https://gamma-api.polymarket.com")


def _make_event_response(slug="btc-updown-5m-1773854100"):
    return [{
        "slug": slug,
        "title": "Bitcoin Up or Down - March 18, 1:15PM-1:20PM ET",
        "markets": [{
            "conditionId": "0xabc123",
            "question": "Bitcoin Up or Down - March 18, 1:15PM-1:20PM ET",
            "outcomes": '["Up", "Down"]',
            "outcomePrices": '["0.52","0.48"]',
            "clobTokenIds": '["token_up_123", "token_down_456"]',
            "closed": False,
            "endDate": "2026-03-18T17:20:00Z",
        }],
    }]


async def test_find_active_market_success(scanner):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_event_response()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.find_active_5min_market("BTC")
    assert result is not None
    assert result["market_id"] == "0xabc123"
    assert result["token_up"] == "token_up_123"
    assert result["token_down"] == "token_down_456"
    assert result["up_price"] == 0.52
    assert result["down_price"] == 0.48


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


async def test_check_resolution_up(scanner):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"resolved": True, "outcomePrices": '["0.99","0.01"]'}]
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.check_resolution("0xabc", token_id="tok123")
    assert result == "Up"


async def test_check_resolution_down(scanner):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"resolved": True, "outcomePrices": '["0.01","0.99"]'}]
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.check_resolution("0xabc", token_id="tok123")
    assert result == "Down"


async def test_check_resolution_no_token():
    scanner = CryptoScanner()
    result = await scanner.check_resolution("0xabc")
    assert result is None


def test_current_window_slug(scanner):
    slug = scanner._current_window_slug("BTC")
    assert slug.startswith("btc-updown-5m-")
    ts = int(slug.split("-")[-1])
    assert ts % 300 == 0


def test_next_window_slug(scanner):
    current = scanner._current_window_slug("BTC")
    next_ = scanner._next_window_slug("BTC")
    current_ts = int(current.split("-")[-1])
    next_ts = int(next_.split("-")[-1])
    assert next_ts - current_ts == 300
