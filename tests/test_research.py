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
