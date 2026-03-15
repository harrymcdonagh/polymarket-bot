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
        self._researcher = RSSResearcher(entry_limit=entry_limit)
        self._static_cache: dict[str, tuple[float, list[dict]]] = {}
        # Apply configurable weights by category
        self._weight_overrides = {
            "rss_google": weight_google,
            "rss_bbc": weight_major, "rss_aljazeera": weight_major,
            "rss_npr": weight_major, "rss_thehill": weight_major,
            "rss_polymarket": weight_prediction, "rss_manifold": weight_prediction,
        }

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
