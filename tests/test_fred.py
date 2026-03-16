import pytest
from unittest.mock import MagicMock, patch
from src.research.fred import FREDSource

@pytest.fixture
def fred():
    return FREDSource(api_key="test-key")

@pytest.fixture
def fred_no_key():
    return FREDSource(api_key="")

def test_fred_available_with_key(fred):
    assert fred.is_available() is True

def test_fred_unavailable_without_key(fred_no_key):
    assert fred_no_key.is_available() is False

def test_fred_name(fred):
    assert fred.name == "fred"

@pytest.mark.asyncio
async def test_fred_economic_market(fred):
    market = MagicMock()
    market.question = "Will the US unemployment rate exceed 5% in 2026?"
    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        series_id = kwargs.get("params", {}).get("series_id", "")
        if series_id == "UNRATE":
            resp.json.return_value = {"observations": [{"value": "4.2"}]}
        elif series_id == "CPIAUCSL":
            resp.json.return_value = {"observations": [{"value": "310.5"}]}
        elif series_id == "FEDFUNDS":
            resp.json.return_value = {"observations": [{"value": "5.25"}]}
        return resp
    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await fred.fetch(market)
    assert result["fred_is_relevant"] == 1.0
    assert result["fred_unemployment"] == 4.2
    assert result["fred_cpi_latest"] == 310.5
    assert result["fred_fed_funds_rate"] == 5.25

@pytest.mark.asyncio
async def test_fred_non_economic_market(fred):
    market = MagicMock()
    market.question = "Will the Lakers win the NBA championship?"
    result = await fred.fetch(market)
    assert result["fred_is_relevant"] == 0.0
    assert result["fred_unemployment"] == 0.0

@pytest.mark.asyncio
async def test_fred_api_error(fred):
    market = MagicMock()
    market.question = "Will inflation exceed 5%?"
    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        result = await fred.fetch(market)
    assert result == {}
