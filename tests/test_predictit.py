import pytest
from unittest.mock import MagicMock, patch
from src.research.predictit import PredictItSource

@pytest.fixture
def predictit():
    return PredictItSource()

def test_predictit_is_available(predictit):
    assert predictit.is_available() is True

def test_predictit_name(predictit):
    assert predictit.name == "predictit"

@pytest.mark.asyncio
async def test_predictit_search_with_match(predictit):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"question": "Will Biden win the 2024 election?", "probability": 0.42, "url": "https://manifold.markets/test", "uniqueBettorCount": 150}]
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await predictit.search("Biden win 2024 election")
    assert len(results) >= 1
    assert "42%" in results[0].text
    assert results[0].source == "predictit"
    assert results[0].weight == 0.85

@pytest.mark.asyncio
async def test_predictit_search_no_match(predictit):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await predictit.search("totally unrelated query")
    assert results == []

@pytest.mark.asyncio
async def test_predictit_error_returns_empty(predictit):
    with patch("httpx.AsyncClient.get", side_effect=Exception("network error")):
        results = await predictit.search("any query")
    assert results == []
