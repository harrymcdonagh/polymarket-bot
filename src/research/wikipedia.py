from __future__ import annotations
import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser
import httpx
from src.research.base import ResearchSource, ResearchResult

logger = logging.getLogger(__name__)
WIKIPEDIA_CURRENT_EVENTS = "https://en.wikipedia.org/api/rest_v1/page/html/Portal%3ACurrent_events"

class _ListItemParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items: list[str] = []
        self._in_li = False
        self._current = ""

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self._in_li = True
            self._current = ""

    def handle_endtag(self, tag):
        if tag == "li" and self._in_li:
            text = self._current.strip()
            if text:
                self.items.append(text)
            self._in_li = False

    def handle_data(self, data):
        if self._in_li:
            self._current += data


def _is_relevant(title: str, query: str, threshold: float = 0.4) -> bool:
    title_lower = title.lower()
    query_lower = query.lower()
    if query_lower in title_lower:
        return True
    query_words = query_lower.split()
    if any(word in title_lower for word in query_words if len(word) > 3):
        return True
    return SequenceMatcher(None, title_lower, query_lower).ratio() >= threshold


class WikipediaSource(ResearchSource):
    """Fetches today's current events from Wikipedia Portal."""
    name = "wikipedia"

    def __init__(self, weight: float = 0.7):
        self.default_weight = weight

    def is_available(self) -> bool:
        return True

    async def search(self, query: str) -> list[ResearchResult]:
        try:
            headers = {"User-Agent": "polymarket-bot/1.0 (research; +https://github.com)"}
            async with httpx.AsyncClient(timeout=10, headers=headers) as client:
                resp = await client.get(WIKIPEDIA_CURRENT_EVENTS)
                if resp.status_code != 200:
                    logger.warning(f"Wikipedia API returned {resp.status_code}")
                    return []
                parser = _ListItemParser()
                parser.feed(resp.text)
            results = []
            for headline in parser.items:
                if _is_relevant(headline, query):
                    results.append(ResearchResult(
                        text=headline,
                        link="https://en.wikipedia.org/wiki/Portal:Current_events",
                        published=datetime.now(timezone.utc),
                        source="wikipedia",
                        weight=self.default_weight,
                    ))
            return results
        except Exception as e:
            logger.warning(f"Wikipedia search failed: {e}")
            return []
