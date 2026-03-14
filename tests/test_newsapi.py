import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import time


def test_newsapi_not_available_without_key():
    from src.research.newsapi import NewsAPISource
    source = NewsAPISource(api_key="")
    assert source.is_available() is False


def test_newsapi_available_with_key():
    from src.research.newsapi import NewsAPISource
    source = NewsAPISource(api_key="test-key")
    assert source.is_available() is True


@pytest.mark.asyncio
async def test_newsapi_search_returns_results():
    from src.research.newsapi import NewsAPISource

    mock_response = {
        "status": "ok",
        "articles": [
            {
                "title": "Breaking News Event",
                "description": "Details about the event",
                "url": "https://example.com/article",
                "publishedAt": "2026-03-14T12:00:00Z",
            }
        ],
    }

    source = NewsAPISource(api_key="test-key", weight=1.0)
    with patch.object(source, "_client") as mock_client:
        mock_client.get_top_headlines.return_value = mock_response
        results = await source.search("breaking event")

    assert len(results) == 1
    assert results[0].text == "Breaking News Event. Details about the event"
    assert results[0].source == "newsapi"
    assert results[0].weight == 1.0
    assert results[0].published is not None


@pytest.mark.asyncio
async def test_newsapi_search_caches_results():
    from src.research.newsapi import NewsAPISource

    mock_response = {"status": "ok", "articles": [
        {"title": "Cached", "description": "Article", "url": "https://x.com", "publishedAt": "2026-03-14T12:00:00Z"}
    ]}

    source = NewsAPISource(api_key="test-key")
    with patch.object(source, "_client") as mock_client:
        mock_client.get_top_headlines.return_value = mock_response
        r1 = await source.search("cache test")
        r2 = await source.search("cache test")

    # Should only call API once
    mock_client.get_top_headlines.assert_called_once()
    assert len(r1) == len(r2)


@pytest.mark.asyncio
async def test_newsapi_search_handles_api_error():
    from src.research.newsapi import NewsAPISource

    source = NewsAPISource(api_key="test-key")
    with patch.object(source, "_client") as mock_client:
        mock_client.get_top_headlines.side_effect = Exception("API error")
        results = await source.search("test query")

    assert results == []


@pytest.mark.asyncio
async def test_newsapi_skips_articles_without_title():
    from src.research.newsapi import NewsAPISource

    mock_response = {
        "status": "ok",
        "articles": [
            {"title": None, "description": "No title", "url": "https://x.com", "publishedAt": "2026-03-14T12:00:00Z"},
            {"title": "Has Title", "description": "Desc", "url": "https://x.com", "publishedAt": "2026-03-14T12:00:00Z"},
        ],
    }

    source = NewsAPISource(api_key="test-key")
    with patch.object(source, "_client") as mock_client:
        mock_client.get_top_headlines.return_value = mock_response
        results = await source.search("test")

    assert len(results) == 1
    assert results[0].text == "Has Title. Desc"
