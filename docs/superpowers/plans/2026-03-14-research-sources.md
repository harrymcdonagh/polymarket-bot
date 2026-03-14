# Expanded Research Sources Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NewsAPI, expanded RSS feeds, and weighted sentiment aggregation to the research pipeline via the Source Adapter Pattern.

**Architecture:** Each research source implements a `ResearchSource` ABC. A `ResearchPipeline` orchestrator fans out queries to all available sources with timeouts, deduplicates results, runs weighted sentiment analysis, and returns a `WeightedSentimentResult`. The existing `Pipeline.research()` delegates to `ResearchPipeline`.

**Tech Stack:** newsapi-python, feedparser, twscrape, difflib, asyncio, pydantic

**Spec:** `docs/superpowers/specs/2026-03-14-research-sources-design.md`

---

## Chunk 1: Foundation

### Task 1: Base Interface & ResearchResult

**Files:**
- Create: `src/research/base.py`
- Create: `tests/test_research_base.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_research_base.py
import pytest
from datetime import datetime, timezone


def test_research_result_creation():
    from src.research.base import ResearchResult
    r = ResearchResult(
        text="Breaking: Event happened",
        link="https://example.com/1",
        published=datetime(2026, 3, 14, tzinfo=timezone.utc),
        source="test",
        weight=0.8,
    )
    assert r.text == "Breaking: Event happened"
    assert r.weight == 0.8
    assert r.source == "test"


def test_research_result_none_published():
    from src.research.base import ResearchResult
    r = ResearchResult(
        text="No date", link="", published=None, source="test", weight=1.0
    )
    assert r.published is None


def test_parse_published_rfc2822():
    from src.research.base import parse_published
    dt = parse_published("Wed, 12 Mar 2026 00:00:00 GMT")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 3


def test_parse_published_iso():
    from src.research.base import parse_published
    dt = parse_published("2026-03-12T15:30:00Z")
    assert dt is not None
    assert dt.year == 2026


def test_parse_published_garbage():
    from src.research.base import parse_published
    assert parse_published("not a date") is None
    assert parse_published("") is None


def test_research_source_abc():
    """ResearchSource cannot be instantiated directly."""
    from src.research.base import ResearchSource
    with pytest.raises(TypeError):
        ResearchSource()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_research_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.research.base'`

- [ ] **Step 3: Implement base.py**

```python
# src/research/base.py
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)


@dataclass
class ResearchResult:
    text: str
    link: str
    published: datetime | None
    source: str
    weight: float


def parse_published(date_str: str) -> datetime | None:
    """Parse various date formats into datetime. Returns None on failure."""
    if not date_str:
        return None
    # Try RFC 2822 (RSS standard)
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # Try ISO 8601
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


class ResearchSource(ABC):
    """Base class for all research sources."""

    name: str
    default_weight: float

    @abstractmethod
    async def search(self, query: str) -> list[ResearchResult]:
        """Search this source for the given query."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this source is configured and usable."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_research_base.py -v`
Expected: All 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/base.py tests/test_research_base.py
git commit -m "feat: add ResearchResult dataclass and ResearchSource ABC"
```

---

### Task 2: NewsAPI Source

**Files:**
- Create: `src/research/newsapi.py`
- Create: `tests/test_newsapi.py`
- Modify: `pyproject.toml` (add `newsapi-python` dependency)

**Context:** Uses `/v2/top-headlines` (free tier). Caches results per-query with 15-minute TTL. Returns `ResearchResult` objects.

- [ ] **Step 1: Add dependency to pyproject.toml**

Add `"newsapi-python>=0.2.7"` to the `dependencies` list in `pyproject.toml`.

- [ ] **Step 2: Install dependency**

Run: `pip install newsapi-python`

- [ ] **Step 3: Write the failing tests**

```python
# tests/test_newsapi.py
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_newsapi.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.research.newsapi'`

- [ ] **Step 5: Implement newsapi.py**

```python
# src/research/newsapi.py
import logging
import time
from newsapi import NewsApiClient
from src.research.base import ResearchSource, ResearchResult, parse_published

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 900  # 15 minutes


class NewsAPISource(ResearchSource):
    name = "newsapi"

    def __init__(self, api_key: str, weight: float = 1.0):
        self.default_weight = weight
        self._api_key = api_key
        self._client = NewsApiClient(api_key=api_key) if api_key else None
        self._cache: dict[str, tuple[float, list[ResearchResult]]] = {}

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str) -> list[ResearchResult]:
        if not self.is_available():
            return []

        now = time.time()
        if query in self._cache:
            cached_at, results = self._cache[query]
            if now - cached_at < CACHE_TTL_SECONDS:
                return results

        try:
            response = self._client.get_top_headlines(q=query, language="en", page_size=100)
            results = []
            for article in response.get("articles", []):
                title = article.get("title")
                if not title:
                    continue
                desc = article.get("description") or ""
                results.append(ResearchResult(
                    text=f"{title}. {desc}" if desc else title,
                    link=article.get("url", ""),
                    published=parse_published(article.get("publishedAt", "")),
                    source=self.name,
                    weight=self.default_weight,
                ))
            self._cache[query] = (now, results)
            return results
        except Exception as e:
            logger.warning(f"NewsAPI search failed for '{query}': {e}")
            return []
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_newsapi.py -v`
Expected: All 6 PASS

- [ ] **Step 7: Commit**

```bash
git add src/research/newsapi.py tests/test_newsapi.py pyproject.toml
git commit -m "feat: add NewsAPI source with caching and top-headlines endpoint"
```

---

### Task 3: Expand RSS Source with Feed Registry

**Files:**
- Modify: `src/research/rss.py`
- Modify: `tests/test_research.py` (add new RSS tests)

**Context:** Add a feed registry with verified URLs and per-feed weights. Static feeds (BBC, Al Jazeera, etc.) are fetched in full and filtered for query relevance. Query feeds (Google News) substitute `{query}` into the URL. Each feed result carries its specific source tag and weight.

- [ ] **Step 1: Write the failing tests**

Add these to `tests/test_research.py`:

```python
# Add to existing tests/test_research.py

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_research.py::test_rss_feed_registry_has_entries tests/test_research.py::test_rss_source_is_always_available tests/test_research.py::test_rss_source_search_returns_research_results tests/test_research.py::test_rss_relevance_filter -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement the expanded rss.py**

Replace `src/research/rss.py` with:

```python
# src/research/rss.py
import logging
import time
from difflib import SequenceMatcher
from urllib.parse import quote

import feedparser

from src.research.base import ResearchSource, ResearchResult, parse_published

logger = logging.getLogger(__name__)

STATIC_CACHE_TTL = 900  # 15 minutes for static feeds

FEED_REGISTRY = [
    # Query feeds — {query} is substituted
    {
        "url": "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
        "weight": 0.7,
        "source_tag": "rss_google",
        "is_query_feed": True,
    },
    # Static feeds — fetched in full, filtered for relevance
    {
        "url": "https://feeds.bbci.co.uk/news/rss.xml",
        "weight": 0.9,
        "source_tag": "rss_bbc",
        "is_query_feed": False,
    },
    {
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "weight": 0.9,
        "source_tag": "rss_aljazeera",
        "is_query_feed": False,
    },
    {
        "url": "https://feeds.npr.org/1001/rss.xml",
        "weight": 0.9,
        "source_tag": "rss_npr",
        "is_query_feed": False,
    },
    {
        "url": "https://thehill.com/news/feed/",
        "weight": 0.9,
        "source_tag": "rss_thehill",
        "is_query_feed": False,
    },
    # Prediction market feeds
    {
        "url": "https://news.polymarket.com/feed",
        "weight": 0.8,
        "source_tag": "rss_polymarket",
        "is_query_feed": False,
    },
    {
        "url": "https://news.manifold.markets/feed",
        "weight": 0.8,
        "source_tag": "rss_manifold",
        "is_query_feed": False,
    },
]


def _is_relevant(title: str, query: str, threshold: float = 0.4) -> bool:
    """Check if a title is relevant to a query via fuzzy matching."""
    title_lower = title.lower()
    query_lower = query.lower()
    # Direct substring match first
    if query_lower in title_lower:
        return True
    # Check individual query words
    query_words = query_lower.split()
    if any(word in title_lower for word in query_words if len(word) > 3):
        return True
    # Fuzzy match fallback
    return SequenceMatcher(None, title_lower, query_lower).ratio() >= threshold


class RSSResearcher:
    """Low-level RSS feed parser. Preserved for backward compatibility."""

    def __init__(self, extra_feeds: list[str] | None = None, entry_limit: int = 20):
        self.extra_feeds = extra_feeds or []
        self.entry_limit = entry_limit
        self._cache: dict[str, list[dict]] = {}

    def search(self, query: str) -> list[dict]:
        """Search Google News RSS and any extra feeds for a query."""
        if query in self._cache:
            return self._cache[query]

        results = []
        encoded_query = quote(query)
        feed_urls = [
            f["url"].format(query=encoded_query)
            for f in FEED_REGISTRY
            if f["is_query_feed"]
        ] + self.extra_feeds

        for url in feed_urls:
            results.extend(self.parse_feed(url))

        self._cache[query] = results
        return results

    def clear_cache(self):
        self._cache.clear()

    def parse_feed(self, url_or_path: str) -> list[dict]:
        """Parse a single RSS feed and return entries."""
        results = []
        try:
            feed = feedparser.parse(url_or_path)
            for entry in feed.entries[: self.entry_limit]:
                title = entry.get("title", "")
                desc = entry.get("description", entry.get("summary", ""))
                results.append(
                    {
                        "title": title,
                        "text": f"{title}. {desc[:500]}",
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "source": "rss",
                    }
                )
        except Exception as e:
            logger.warning(f"RSS parse failed for {url_or_path}: {e}")
        return results


class RSSSource(ResearchSource):
    """RSS adapter conforming to ResearchSource interface."""

    name = "rss"

    def __init__(
        self,
        feeds: list[dict] | None = None,
        entry_limit: int = 20,
        weight_google: float = 0.7,
        weight_major: float = 0.9,
        weight_prediction: float = 0.8,
    ):
        self.feeds = feeds if feeds is not None else FEED_REGISTRY
        self.default_weight = 0.7  # varies per feed, this is fallback
        # Apply configurable weights by category
        self._weight_overrides = {
            "rss_google": weight_google,
            "rss_bbc": weight_major, "rss_aljazeera": weight_major,
            "rss_npr": weight_major, "rss_thehill": weight_major,
            "rss_polymarket": weight_prediction, "rss_manifold": weight_prediction,
        }
        self._researcher = RSSResearcher(entry_limit=entry_limit)
        self._static_cache: dict[str, tuple[float, list[dict]]] = {}

    def is_available(self) -> bool:
        return True  # RSS needs no API keys

    async def search(self, query: str) -> list[ResearchResult]:
        results = []
        for feed in self.feeds:
            entries = self._fetch_feed(feed, query)
            source_tag = feed["source_tag"]
            weight = self._weight_overrides.get(source_tag, feed["weight"])

            for entry in entries:
                title = entry.get("title", "")
                # Filter static feeds for relevance
                if not feed["is_query_feed"] and not _is_relevant(title, query):
                    continue
                results.append(
                    ResearchResult(
                        text=entry["text"],
                        link=entry.get("link", ""),
                        published=parse_published(entry.get("published", "")),
                        source=source_tag,
                        weight=weight,
                    )
                )
        return results

    def _fetch_feed(self, feed: dict, query: str) -> list[dict]:
        url = feed["url"]
        if feed["is_query_feed"]:
            url = url.format(query=quote(query))
            return self._researcher.parse_feed(url)

        # Static feed — use TTL cache
        now = time.time()
        if url in self._static_cache:
            cached_at, entries = self._static_cache[url]
            if now - cached_at < STATIC_CACHE_TTL:
                return entries

        entries = self._researcher.parse_feed(url)
        self._static_cache[url] = (now, entries)
        return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_research.py -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
git add src/research/rss.py tests/test_research.py
git commit -m "feat: expand RSS with feed registry, static feed caching, and relevance filtering"
```

---

### Task 4: Twitter & Reddit Source Adapters

**Files:**
- Modify: `src/research/twitter.py`
- Modify: `src/research/reddit.py`
- Modify: `tests/test_research.py` (add adapter tests)

**Context:** Add thin `TwitterSource` and `RedditSource` adapter classes conforming to `ResearchSource`. The existing `TwitterResearcher` and `RedditResearcher` classes stay unchanged — the adapters wrap them.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_research.py`:

```python
@pytest.mark.asyncio
async def test_twitter_source_wraps_researcher():
    from src.research.twitter import TwitterSource

    mock_tweet = MagicMock()
    mock_tweet.rawContent = "Tweet about elections"
    mock_tweet.date = "2026-03-14"
    mock_tweet.likeCount = 5

    async def mock_search(query, limit=50):
        for t in [mock_tweet]:
            yield t

    mock_api = MagicMock()
    mock_api.search = mock_search

    source = TwitterSource(api=mock_api)
    assert source.is_available() is True
    results = await source.search("elections")
    assert len(results) == 1
    assert results[0].source == "twitter"
    assert results[0].weight == 0.5


def test_twitter_source_not_available_when_api_fails():
    from src.research.twitter import TwitterSource
    source = TwitterSource(api=None)
    # Force the availability check to fail
    source._checked_available = False
    assert source.is_available() is False


def test_reddit_source_not_available_without_credentials():
    from src.research.reddit import RedditSource
    from src.config import Settings
    s = Settings(REDDIT_CLIENT_ID="", REDDIT_CLIENT_SECRET="")
    source = RedditSource(settings=s)
    assert source.is_available() is False


def test_reddit_source_available_with_credentials():
    from src.research.reddit import RedditSource
    from src.config import Settings
    s = Settings(REDDIT_CLIENT_ID="abc", REDDIT_CLIENT_SECRET="xyz")
    source = RedditSource(settings=s)
    assert source.is_available() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_research.py::test_twitter_source_wraps_researcher tests/test_research.py::test_twitter_source_not_available_without_api tests/test_research.py::test_reddit_source_not_available_without_credentials tests/test_research.py::test_reddit_source_available_with_credentials -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Add TwitterSource to twitter.py**

Append to end of `src/research/twitter.py`:

```python
from src.research.base import ResearchSource, ResearchResult, parse_published


class TwitterSource(ResearchSource):
    """Twitter adapter conforming to ResearchSource interface."""

    name = "twitter"
    default_weight = 0.5

    def __init__(self, api=None, weight: float = 0.5):
        self.default_weight = weight
        self._api = api
        self._researcher = None
        self._checked_available: bool | None = None

    def is_available(self) -> bool:
        """Check if twscrape has logged-in accounts. Lazy-inits API if needed."""
        if self._checked_available is not None:
            return self._checked_available
        try:
            if self._api is None:
                self._api = API()
            self._researcher = TwitterResearcher(api=self._api)
            self._checked_available = True
            return True
        except Exception:
            self._checked_available = False
            return False

    async def search(self, query: str) -> list[ResearchResult]:
        if not self.is_available():
            return []
        raw = await self._researcher.search(query)
        return [
            ResearchResult(
                text=r["text"],
                link="",
                published=parse_published(r.get("date", "")),
                source=self.name,
                weight=self.default_weight,
            )
            for r in raw
        ]
```

- [ ] **Step 4: Add RedditSource to reddit.py**

Append to end of `src/research/reddit.py`:

```python
import asyncio
from src.research.base import ResearchSource, ResearchResult


class RedditSource(ResearchSource):
    """Reddit adapter conforming to ResearchSource interface."""

    name = "reddit"
    default_weight = 0.6

    def __init__(self, settings=None, weight: float = 0.6):
        self.default_weight = weight
        self._settings = settings
        self._researcher = None

    def is_available(self) -> bool:
        s = self._settings
        if s is None:
            return False
        return bool(s.REDDIT_CLIENT_ID and s.REDDIT_CLIENT_SECRET)

    async def search(self, query: str) -> list[ResearchResult]:
        if not self.is_available():
            return []
        if self._researcher is None:
            self._researcher = RedditResearcher(settings=self._settings)
        raw = await asyncio.to_thread(self._researcher.search, query)
        return [
            ResearchResult(
                text=r["text"],
                link="",
                published=None,
                source=self.name,
                weight=self.default_weight,
            )
            for r in raw
        ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_research.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/research/twitter.py src/research/reddit.py tests/test_research.py
git commit -m "feat: add TwitterSource and RedditSource adapters"
```

---

## Chunk 2: Pipeline & Integration

### Task 5: Research Pipeline with Weighted Aggregation

**Files:**
- Create: `src/research/pipeline.py`
- Create: `tests/test_research_pipeline.py`

**Context:** The `ResearchPipeline` fans out queries to all available sources with timeouts, deduplicates results, runs sentiment analysis with source weights, and returns a `WeightedSentimentResult`. This is the core orchestrator.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_research_pipeline.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from src.research.base import ResearchResult


def _make_result(text, source="test", weight=1.0):
    return ResearchResult(
        text=text, link="", published=datetime(2026, 3, 14, tzinfo=timezone.utc),
        source=source, weight=weight,
    )


def test_dedup_keeps_highest_weight():
    from src.research.pipeline import deduplicate
    results = [
        _make_result("US Election Results Show Surprise", source="rss_google", weight=0.7),
        _make_result("US Election Results Show Surprise Outcome", source="rss_bbc", weight=0.9),
    ]
    deduped = deduplicate(results, threshold=0.85)
    assert len(deduped) == 1
    assert deduped[0].source == "rss_bbc"


def test_dedup_keeps_different_articles():
    from src.research.pipeline import deduplicate
    results = [
        _make_result("US Election Results", source="a", weight=0.7),
        _make_result("Crypto Market Crash", source="b", weight=0.9),
    ]
    deduped = deduplicate(results, threshold=0.85)
    assert len(deduped) == 2


@pytest.mark.asyncio
async def test_pipeline_search_fans_out():
    from src.research.pipeline import ResearchPipeline

    source1 = MagicMock()
    source1.is_available.return_value = True
    source1.name = "src1"
    source1.search = AsyncMock(return_value=[_make_result("Result 1", "src1", 0.9)])

    source2 = MagicMock()
    source2.is_available.return_value = True
    source2.name = "src2"
    source2.search = AsyncMock(return_value=[_make_result("Result 2", "src2", 0.7)])

    pipeline = ResearchPipeline(sources=[source1, source2], timeout=10)
    results = await pipeline.search("test query")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_pipeline_skips_unavailable_sources():
    from src.research.pipeline import ResearchPipeline

    available = MagicMock()
    available.is_available.return_value = True
    available.name = "available"
    available.search = AsyncMock(return_value=[_make_result("Got it", "available")])

    unavailable = MagicMock()
    unavailable.is_available.return_value = False
    unavailable.name = "unavailable"

    pipeline = ResearchPipeline(sources=[available, unavailable], timeout=10)
    results = await pipeline.search("test")
    assert len(results) == 1
    unavailable.search.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_handles_source_timeout():
    from src.research.pipeline import ResearchPipeline
    import asyncio

    slow_source = MagicMock()
    slow_source.is_available.return_value = True
    slow_source.name = "slow"

    async def slow_search(query):
        await asyncio.sleep(10)
        return []

    slow_source.search = slow_search

    fast_source = MagicMock()
    fast_source.is_available.return_value = True
    fast_source.name = "fast"
    fast_source.search = AsyncMock(return_value=[_make_result("Fast result")])

    pipeline = ResearchPipeline(sources=[slow_source, fast_source], timeout=0.1)
    results = await pipeline.search("test")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_pipeline_weighted_sentiment():
    from src.research.pipeline import ResearchPipeline

    source = MagicMock()
    source.is_available.return_value = True
    source.name = "test"
    source.search = AsyncMock(return_value=[
        _make_result("Great positive news!", "newsapi", 1.0),
        _make_result("Terrible negative news!", "twitter", 0.5),
    ])

    mock_analyzer = MagicMock()
    mock_analyzer.analyze_batch.return_value = [
        {"label": "positive", "score": 0.9},
        {"label": "negative", "score": 0.8},
    ]

    pipeline = ResearchPipeline(sources=[source], timeout=10, sentiment_analyzer=mock_analyzer)
    sentiment = await pipeline.search_and_analyze("test")

    assert "weighted_avg_score" in sentiment
    assert "source_breakdown" in sentiment
    assert sentiment["sample_size"] == 2


@pytest.mark.asyncio
async def test_pipeline_empty_results():
    from src.research.pipeline import ResearchPipeline

    source = MagicMock()
    source.is_available.return_value = True
    source.name = "empty"
    source.search = AsyncMock(return_value=[])

    pipeline = ResearchPipeline(sources=[source], timeout=10)
    sentiment = await pipeline.search_and_analyze("nothing")
    assert sentiment["sample_size"] == 0
    assert sentiment["weighted_avg_score"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_research_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement pipeline.py**

```python
# src/research/pipeline.py
import asyncio
import logging
from difflib import SequenceMatcher

from src.research.base import ResearchSource, ResearchResult
from src.research.sentiment import SentimentAnalyzer

logger = logging.getLogger(__name__)


def deduplicate(results: list[ResearchResult], threshold: float = 0.85) -> list[ResearchResult]:
    """Remove near-duplicate results, keeping the one with highest weight."""
    if not results:
        return []
    kept: list[ResearchResult] = []
    for result in results:
        is_dup = False
        for i, existing in enumerate(kept):
            ratio = SequenceMatcher(None, result.text.lower(), existing.text.lower()).ratio()
            if ratio >= threshold:
                # Keep the one with higher weight
                if result.weight > existing.weight:
                    kept[i] = result
                is_dup = True
                break
        if not is_dup:
            kept.append(result)
    return kept


class ResearchPipeline:
    """Orchestrates research across all available sources with weighted aggregation."""

    def __init__(
        self,
        sources: list[ResearchSource],
        timeout: float = 10.0,
        sentiment_analyzer: SentimentAnalyzer | None = None,
    ):
        self.sources = sources
        self.timeout = timeout
        self.sentiment = sentiment_analyzer or SentimentAnalyzer(use_transformer=False)

    async def search(self, query: str) -> list[ResearchResult]:
        """Fan out query to all available sources, deduplicate results."""
        available = [s for s in self.sources if s.is_available()]
        if not available:
            logger.warning("No research sources available")
            return []

        tasks = []
        source_names = []
        for source in available:
            tasks.append(self._search_with_timeout(source, query))
            source_names.append(source.name)

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[ResearchResult] = []
        for name, result in zip(source_names, raw_results):
            if isinstance(result, Exception):
                logger.warning(f"Source '{name}' failed: {result}")
                continue
            all_results.extend(result)

        deduped = deduplicate(all_results)
        logger.info(f"Research: {len(all_results)} results from {len(available)} sources, {len(deduped)} after dedup")
        return deduped

    async def search_and_analyze(self, query: str) -> dict:
        """Search all sources and return weighted sentiment analysis."""
        results = await self.search(query)
        if not results:
            return {
                "positive_ratio": 0, "negative_ratio": 0, "neutral_ratio": 0,
                "weighted_avg_score": 0, "sample_size": 0, "source_breakdown": {},
            }

        texts = [r.text for r in results]
        sentiments = self.sentiment.analyze_batch(texts)

        # Weighted aggregation
        total_weight = 0
        weighted_score = 0
        pos_weight = 0
        neg_weight = 0
        neu_weight = 0
        source_breakdown: dict[str, dict] = {}

        for result, sent in zip(results, sentiments):
            w = result.weight
            total_weight += w
            weighted_score += sent["score"] * w

            if sent["label"] == "positive":
                pos_weight += w
            elif sent["label"] == "negative":
                neg_weight += w
            else:
                neu_weight += w

            # Track per-source stats
            src = result.source
            if src not in source_breakdown:
                source_breakdown[src] = {"count": 0, "total_score": 0, "pos": 0, "neg": 0, "neu": 0}
            source_breakdown[src]["count"] += 1
            source_breakdown[src]["total_score"] += sent["score"]
            if sent["label"] == "positive":
                source_breakdown[src]["pos"] += 1
            elif sent["label"] == "negative":
                source_breakdown[src]["neg"] += 1
            else:
                source_breakdown[src]["neu"] += 1

        # Finalize source breakdown with per-source ratios
        for src in source_breakdown:
            count = source_breakdown[src]["count"]
            source_breakdown[src]["avg_score"] = source_breakdown[src].pop("total_score") / count
            source_breakdown[src]["positive_ratio"] = source_breakdown[src].pop("pos") / count
            source_breakdown[src]["negative_ratio"] = source_breakdown[src].pop("neg") / count
            source_breakdown[src]["neutral_ratio"] = source_breakdown[src].pop("neu") / count

        return {
            "positive_ratio": pos_weight / total_weight if total_weight else 0,
            "negative_ratio": neg_weight / total_weight if total_weight else 0,
            "neutral_ratio": neu_weight / total_weight if total_weight else 0,
            "weighted_avg_score": weighted_score / total_weight if total_weight else 0,
            "sample_size": len(results),
            "source_breakdown": source_breakdown,
        }

    async def _search_with_timeout(self, source: ResearchSource, query: str) -> list[ResearchResult]:
        try:
            return await asyncio.wait_for(source.search(query), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Source '{source.name}' timed out after {self.timeout}s")
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_research_pipeline.py -v`
Expected: All 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/pipeline.py tests/test_research_pipeline.py
git commit -m "feat: add ResearchPipeline with weighted aggregation and deduplication"
```

---

### Task 6: Configuration — New Settings Fields

**Files:**
- Modify: `src/config.py`

**Context:** Add new settings for source weights, NewsAPI key, and research timeout. All weights validated to 0 < w <= 1.

- [ ] **Step 1: Write failing tests for weight validation**

Add to a new section at bottom of existing config tests, or add inline:

```python
# Run these as one-off assertions in the test step
python -m pytest -xvs -k "test_weight" tests/test_config_weights.py
```

```python
# tests/test_config_weights.py
import pytest
from src.config import Settings


def test_source_weight_defaults():
    s = Settings()
    assert s.SOURCE_WEIGHT_NEWSAPI == 1.0
    assert s.SOURCE_WEIGHT_RSS_MAJOR == 0.9
    assert s.SOURCE_WEIGHT_TWITTER == 0.5


def test_source_weight_rejects_zero():
    with pytest.raises(Exception):
        Settings(SOURCE_WEIGHT_NEWSAPI=0.0)


def test_source_weight_rejects_over_one():
    with pytest.raises(Exception):
        Settings(SOURCE_WEIGHT_NEWSAPI=1.5)


def test_source_weight_accepts_valid():
    s = Settings(SOURCE_WEIGHT_NEWSAPI=0.5)
    assert s.SOURCE_WEIGHT_NEWSAPI == 0.5


def test_newsapi_key_default_empty():
    s = Settings()
    assert s.NEWSAPI_KEY == ""


def test_research_timeout_default():
    s = Settings()
    assert s.RESEARCH_TIMEOUT == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config_weights.py -v`
Expected: FAIL — missing fields

- [ ] **Step 3: Add settings fields to config.py**

Add after the existing `SENTIMENT_AMBIGUITY_THRESHOLD` line:

```python
    # Research source weights
    NEWSAPI_KEY: str = ""
    SOURCE_WEIGHT_NEWSAPI: float = 1.0
    SOURCE_WEIGHT_RSS_MAJOR: float = 0.9
    SOURCE_WEIGHT_RSS_PREDICTION: float = 0.8
    SOURCE_WEIGHT_RSS_GOOGLE: float = 0.7
    SOURCE_WEIGHT_TWITTER: float = 0.5
    SOURCE_WEIGHT_REDDIT: float = 0.6
    RESEARCH_TIMEOUT: int = 10
```

Add a field validator:

```python
    @field_validator(
        "SOURCE_WEIGHT_NEWSAPI", "SOURCE_WEIGHT_RSS_MAJOR",
        "SOURCE_WEIGHT_RSS_PREDICTION", "SOURCE_WEIGHT_RSS_GOOGLE",
        "SOURCE_WEIGHT_TWITTER", "SOURCE_WEIGHT_REDDIT",
    )
    @classmethod
    def weight_range(cls, v: float) -> float:
        if not 0 < v <= 1:
            raise ValueError("Source weight must be between 0 (exclusive) and 1 (inclusive)")
        return v
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config_weights.py -v`
Expected: All 6 PASS

- [ ] **Step 5: Run full test suite to verify nothing breaks**

Run: `python -m pytest tests/ -v`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_config_weights.py
git commit -m "feat: add research source weight settings and NEWSAPI_KEY"
```

---

### Task 7: Integrate ResearchPipeline into Main Pipeline

**Files:**
- Modify: `src/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Context:** Refactor `Pipeline.__init__` to create a `ResearchPipeline` with all sources. Refactor `Pipeline.research()` to delegate to it. Remove `_search_twitter()`, `_search_reddit()` private methods. Preserve `ResearchReport` and `SentimentResult` output interface.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_uses_research_pipeline(tmp_path):
    """Pipeline.research() should delegate to ResearchPipeline."""
    from src.research.pipeline import ResearchPipeline

    settings = Settings(ANTHROPIC_API_KEY="test")

    with patch("src.pipeline.MarketScanner"):
        pipeline = Pipeline(settings=settings, db_path=str(tmp_path / "test.db"))

    assert hasattr(pipeline, "research_pipeline")
    assert isinstance(pipeline.research_pipeline, ResearchPipeline)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py::test_pipeline_uses_research_pipeline -v`
Expected: FAIL — `AttributeError: 'Pipeline' object has no attribute 'research_pipeline'`

- [ ] **Step 3: Refactor Pipeline.__init__ and research()**

In `src/pipeline.py`:

1. Add imports at top:
```python
from src.research.pipeline import ResearchPipeline
from src.research.newsapi import NewsAPISource
from src.research.twitter import TwitterSource
from src.research.reddit import RedditSource
from src.research.rss import RSSSource
```

2. In `__init__`, replace the `self._twitter`, `self._reddit`, `self._rss` block with:
```python
        # Research pipeline with all sources
        self.research_pipeline = ResearchPipeline(
            sources=[
                NewsAPISource(
                    api_key=self.settings.NEWSAPI_KEY,
                    weight=self.settings.SOURCE_WEIGHT_NEWSAPI,
                ),
                RSSSource(
                    entry_limit=self.settings.RSS_ENTRY_LIMIT,
                    weight_google=self.settings.SOURCE_WEIGHT_RSS_GOOGLE,
                    weight_major=self.settings.SOURCE_WEIGHT_RSS_MAJOR,
                    weight_prediction=self.settings.SOURCE_WEIGHT_RSS_PREDICTION,
                ),
                TwitterSource(weight=self.settings.SOURCE_WEIGHT_TWITTER),
                RedditSource(
                    settings=self.settings,
                    weight=self.settings.SOURCE_WEIGHT_REDDIT,
                ),
            ],
            timeout=self.settings.RESEARCH_TIMEOUT,
            sentiment_analyzer=self.sentiment,
        )
```

3. Replace the `research()` method body:
```python
    async def research(self, market: ScannedMarket) -> ResearchReport:
        logger.info(f"=== STEP 2: Researching '{market.question[:60]}' ===")
        query = market.question

        weighted_result = await self.research_pipeline.search_and_analyze(query)

        # Convert to SentimentResult objects for backward compat
        # Uses per-source ratios from breakdown, not global ratios
        sentiments = []
        for source_name, breakdown in weighted_result["source_breakdown"].items():
            sentiments.append(SentimentResult(
                source=source_name,
                query=query,
                positive_ratio=breakdown.get("positive_ratio", 0),
                negative_ratio=breakdown.get("negative_ratio", 0),
                neutral_ratio=breakdown.get("neutral_ratio", 0),
                sample_size=breakdown["count"],
                avg_compound_score=breakdown["avg_score"],
                collected_at=datetime.now(timezone.utc),
            ))

        narrative = await self._generate_narrative(market, sentiments)

        return ResearchReport(
            market_id=market.condition_id,
            question=market.question,
            sentiments=sentiments,
            narrative_summary=narrative,
            narrative_vs_odds_alignment=self._calc_alignment(sentiments, market.yes_price),
            researched_at=datetime.now(timezone.utc),
        )
```

4. Remove `_search_twitter()` and `_search_reddit()` methods.

5. Remove unused imports: `TwitterResearcher`, `RedditResearcher`, `RSSResearcher`.

- [ ] **Step 4: Update existing pipeline tests**

The existing `test_pipeline_dry_run_cycle` and `test_pipeline_saves_snapshots` patch `_search_twitter`, `_search_reddit`, and `_rss` which no longer exist. Update them to patch `research_pipeline.search_and_analyze` instead:

```python
@pytest.mark.asyncio
async def test_pipeline_dry_run_cycle(tmp_path):
    """Test a full dry-run cycle with mocked research pipeline."""
    settings = Settings(ANTHROPIC_API_KEY="test")
    market = _mock_market()

    with patch("src.pipeline.MarketScanner") as MockScanner, \
         patch("src.pipeline.ResearchPipeline") as MockRP, \
         patch.object(Pipeline, "_generate_narrative", new_callable=AsyncMock, return_value="Test narrative"):

        MockScanner.return_value.scan = AsyncMock(return_value=[market])
        MockRP.return_value.search_and_analyze = AsyncMock(return_value={
            "positive_ratio": 0.5, "negative_ratio": 0.3, "neutral_ratio": 0.2,
            "weighted_avg_score": 0.6, "sample_size": 5,
            "source_breakdown": {"rss_google": {"count": 5, "avg_score": 0.6}},
        })

        pipeline = Pipeline(settings=settings, db_path=str(tmp_path / "test.db"))
        pipeline.postmortem = MagicMock()
        pipeline.postmortem.run_full_postmortem = AsyncMock(return_value=[])

        await pipeline.run_cycle(dry_run=True)
```

Apply similar changes to `test_pipeline_saves_snapshots`.

- [ ] **Step 5: Run all pipeline tests**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: integrate ResearchPipeline into main Pipeline, remove direct source calls"
```

---

### Task 8: Update .env.example

**Files:**
- Modify: `.env.example`

**Context:** Add the new `NEWSAPI_KEY` and source weight config entries so users know what's available.

- [ ] **Step 1: Add new entries to .env.example**

Add to `.env.example`:

```
# NewsAPI (free tier: 100 req/day, top-headlines only)
NEWSAPI_KEY=

# Research source weights (0 < weight <= 1.0)
# SOURCE_WEIGHT_NEWSAPI=1.0
# SOURCE_WEIGHT_RSS_MAJOR=0.9
# SOURCE_WEIGHT_RSS_PREDICTION=0.8
# SOURCE_WEIGHT_RSS_GOOGLE=0.7
# SOURCE_WEIGHT_TWITTER=0.5
# SOURCE_WEIGHT_REDDIT=0.6
# RESEARCH_TIMEOUT=10
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add research source settings to .env.example"
```

---

### Task 9: Dashboard Integration — Source Weights in Settings

**Files:**
- Modify: `src/dashboard/service.py`
- Modify: `src/dashboard/web.py` (if settings endpoint needs updating)

**Context:** The `UPDATABLE_SETTINGS` set in `service.py` line 17-19 controls which settings can be changed from the dashboard. Add the new source weight settings so they're editable from the dashboard.

- [ ] **Step 1: Update UPDATABLE_SETTINGS in service.py**

In `src/dashboard/service.py`, update the `UPDATABLE_SETTINGS` set to include the new source weight fields:

```python
UPDATABLE_SETTINGS = {
    "BANKROLL", "MAX_BET_FRACTION", "CONFIDENCE_THRESHOLD",
    "MIN_EDGE_THRESHOLD", "MAX_DAILY_LOSS", "LOOP_INTERVAL",
    "SOURCE_WEIGHT_NEWSAPI", "SOURCE_WEIGHT_RSS_MAJOR",
    "SOURCE_WEIGHT_RSS_PREDICTION", "SOURCE_WEIGHT_RSS_GOOGLE",
    "SOURCE_WEIGHT_TWITTER", "SOURCE_WEIGHT_REDDIT",
    "RESEARCH_TIMEOUT",
}
```

- [ ] **Step 2: Also add the setting validators for the new fields**

In `src/dashboard/service.py`, update `_SETTING_VALIDATORS` to include weight validation:

```python
# Add to existing _SETTING_VALIDATORS dict
"SOURCE_WEIGHT_NEWSAPI": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
"SOURCE_WEIGHT_RSS_MAJOR": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
"SOURCE_WEIGHT_RSS_PREDICTION": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
"SOURCE_WEIGHT_RSS_GOOGLE": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
"SOURCE_WEIGHT_TWITTER": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
"SOURCE_WEIGHT_REDDIT": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
"RESEARCH_TIMEOUT": lambda v: v >= 1 or "RESEARCH_TIMEOUT must be >= 1",
```

- [ ] **Step 3: Run dashboard tests**

Run: `python -m pytest tests/test_dashboard_service.py tests/test_web.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/service.py
git commit -m "feat: add source weight settings to dashboard"
```

---

### Task 10: Final Integration Test

**Files:**
- No new files — this is a verification task.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Smoke test the pipeline imports**

Run: `python -c "from src.research.pipeline import ResearchPipeline; from src.research.rss import RSSSource; from src.research.newsapi import NewsAPISource; from src.research.twitter import TwitterSource; from src.research.reddit import RedditSource; from src.research.base import ResearchResult, ResearchSource; print('All imports OK')"`
Expected: "All imports OK"

- [ ] **Step 3: Verify source weights are configurable**

Run: `python -c "from src.config import Settings; s = Settings(); print(f'NewsAPI weight: {s.SOURCE_WEIGHT_NEWSAPI}'); print(f'RSS major weight: {s.SOURCE_WEIGHT_RSS_MAJOR}'); print(f'Timeout: {s.RESEARCH_TIMEOUT}s')"`
Expected: Shows default weight values

- [ ] **Step 4: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: integration fixups from final testing"
```
