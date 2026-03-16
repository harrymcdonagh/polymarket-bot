import pytest
from unittest.mock import MagicMock, patch
from src.research.metaculus import MetaculusSource

@pytest.fixture
def metaculus():
    return MetaculusSource()

def test_metaculus_is_available(metaculus):
    assert metaculus.is_available() is True

def test_metaculus_name(metaculus):
    assert metaculus.name == "metaculus"

@pytest.mark.asyncio
async def test_metaculus_search(metaculus):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{"title": "Will X happen by 2026?", "community_prediction": {"full": {"q2": 0.73}}, "number_of_forecasters": 847, "page_url": "/questions/12345/"}]
    }
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await metaculus.search("X happen 2026")
    assert len(results) == 1
    assert "73%" in results[0].text
    assert "847" in results[0].text
    assert results[0].source == "metaculus"
    assert results[0].weight == 0.9

@pytest.mark.asyncio
async def test_metaculus_empty_on_error(metaculus):
    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        results = await metaculus.search("anything")
    assert results == []
