import pytest
from unittest.mock import AsyncMock, patch, MagicMock, PropertyMock
from src.research.twitter import TwitterResearcher
from src.research.reddit import RedditResearcher
from src.research.rss import RSSResearcher


@pytest.mark.asyncio
async def test_twitter_search_returns_texts():
    mock_tweet = MagicMock()
    mock_tweet.rawContent = "This market is going to resolve YES for sure"
    mock_tweet.date = "2026-03-12"
    mock_tweet.likeCount = 10

    # Create a proper async iterator for `async for`
    async def mock_search(query, limit=50):
        for tweet in [mock_tweet]:
            yield tweet

    mock_api = MagicMock()
    mock_api.search = mock_search
    researcher = TwitterResearcher(mock_api)
    results = await researcher.search("prediction market question", limit=10)
    assert len(results) >= 1
    assert results[0]["text"] == "This market is going to resolve YES for sure"


def test_reddit_search_returns_texts():
    mock_submission = MagicMock()
    mock_submission.title = "Market X is definitely going YES"
    mock_submission.selftext = "I have strong evidence..."
    mock_submission.score = 42
    mock_submission.num_comments = 10
    mock_submission.created_utc = 1710000000

    mock_reddit = MagicMock()
    mock_reddit.subreddit.return_value.search.return_value = [mock_submission]

    researcher = RedditResearcher(reddit=mock_reddit)
    results = researcher.search("prediction market question", subreddits=["polymarket"])
    assert len(results) >= 1
    assert "Market X" in results[0]["text"]


def test_rss_parse_feed(tmp_path):
    # Create a minimal RSS feed
    feed_xml = """<?xml version="1.0"?>
    <rss version="2.0">
        <channel>
            <title>Test Feed</title>
            <item>
                <title>Market prediction shows strong trend</title>
                <link>http://example.com/1</link>
                <description>Analysis suggests positive outcome</description>
                <pubDate>Wed, 12 Mar 2026 00:00:00 GMT</pubDate>
            </item>
        </channel>
    </rss>"""
    feed_file = tmp_path / "test.xml"
    feed_file.write_text(feed_xml)

    researcher = RSSResearcher()
    results = researcher.parse_feed(str(feed_file))
    assert len(results) == 1
    assert "strong trend" in results[0]["text"]


def test_rss_feed_registry_has_entries():
    from src.research.rss import FEED_REGISTRY
    assert len(FEED_REGISTRY) >= 6
    # Check that each entry has required fields
    for feed in FEED_REGISTRY:
        assert "url" in feed
        assert "weight" in feed
        assert "source_tag" in feed
        assert "is_query_feed" in feed


def test_rss_source_is_always_available():
    from src.research.rss import RSSSource
    source = RSSSource()
    assert source.is_available() is True


@pytest.mark.asyncio
async def test_rss_source_search_returns_research_results():
    from src.research.rss import RSSSource
    from src.research.base import ResearchResult

    source = RSSSource()
    # Mock parse_feed to return predictable data with title key
    source._researcher.parse_feed = MagicMock(return_value=[
        {"title": "Test election news", "text": "Test election news. Details here", "link": "https://x.com", "published": "2026-03-14", "source": "rss"}
    ])
    results = await source.search("election")
    assert all(isinstance(r, ResearchResult) for r in results)


@pytest.mark.asyncio
async def test_rss_source_filters_static_feeds_by_relevance():
    """Integration test: static feed entries are filtered by relevance."""
    from src.research.rss import RSSSource

    # Use a single static feed for this test
    test_feeds = [
        {"url": "https://example.com/feed", "weight": 0.9, "source_tag": "rss_test", "is_query_feed": False},
    ]
    source = RSSSource(feeds=test_feeds)
    source._researcher.parse_feed = MagicMock(return_value=[
        {"title": "US Election Results 2026", "text": "US Election Results 2026. Detailed analysis", "link": "", "published": "", "source": "rss"},
        {"title": "Best recipes for pasta", "text": "Best recipes for pasta. Italian cuisine", "link": "", "published": "", "source": "rss"},
    ])
    results = await source.search("election")
    assert len(results) == 1
    assert "Election" in results[0].text


def test_rss_relevance_filter():
    from src.research.rss import _is_relevant
    assert _is_relevant("US Election Results 2026", "election") is True
    assert _is_relevant("Best recipes for pasta", "election") is False
