import logging
from urllib.parse import quote
import feedparser

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
]


class RSSResearcher:
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
        feed_urls = [f.format(query=encoded_query) for f in DEFAULT_FEEDS] + self.extra_feeds

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
            for entry in feed.entries[:self.entry_limit]:
                title = entry.get("title", "")
                desc = entry.get("description", entry.get("summary", ""))
                results.append({
                    "text": f"{title}. {desc[:500]}",
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "source": "rss",
                })
        except Exception as e:
            logger.warning(f"RSS parse failed for {url_or_path}: {e}")
        return results
