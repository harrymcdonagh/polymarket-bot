import logging
import feedparser

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
]


class RSSResearcher:
    def __init__(self, extra_feeds: list[str] | None = None):
        self.extra_feeds = extra_feeds or []

    def search(self, query: str) -> list[dict]:
        """Search Google News RSS and any extra feeds for a query."""
        results = []
        feed_urls = [f.format(query=query) for f in DEFAULT_FEEDS] + self.extra_feeds

        for url in feed_urls:
            results.extend(self.parse_feed(url))

        return results

    def parse_feed(self, url_or_path: str) -> list[dict]:
        """Parse a single RSS feed and return entries."""
        results = []
        try:
            feed = feedparser.parse(url_or_path)
            for entry in feed.entries[:20]:
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
