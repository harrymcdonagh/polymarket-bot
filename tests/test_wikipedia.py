import pytest
from unittest.mock import MagicMock, patch
from src.research.wikipedia import WikipediaSource

@pytest.fixture
def wiki():
    return WikipediaSource()

def test_wikipedia_is_available(wiki):
    assert wiki.is_available() is True

def test_wikipedia_name(wiki):
    assert wiki.name == "wikipedia"

@pytest.mark.asyncio
async def test_wikipedia_search(wiki):
    html = "<ul><li>Biden signs new executive order on AI regulation</li><li>Earthquake strikes Turkey</li><li>SpaceX launches Starship</li></ul>"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await wiki.search("Biden executive order AI")
    assert len(results) >= 1
    assert "Biden" in results[0].text
    assert results[0].source == "wikipedia"
    assert results[0].weight == 0.7

@pytest.mark.asyncio
async def test_wikipedia_no_matches(wiki):
    html = "<ul><li>Unrelated headline about football</li></ul>"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await wiki.search("quantum computing breakthrough")
    assert results == []

@pytest.mark.asyncio
async def test_wikipedia_error_returns_empty(wiki):
    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        results = await wiki.search("anything")
    assert results == []
