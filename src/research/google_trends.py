"""Google Trends research source — tracks search interest for market topics."""
import logging
from datetime import datetime, timezone

from src.research.base import ResearchSource, ResearchResult

logger = logging.getLogger(__name__)


class GoogleTrendsSource(ResearchSource):
    """Fetches Google Trends data for prediction market queries.

    Search interest spikes often correlate with event probability shifts.
    Uses pytrends library (unofficial Google Trends API).
    """

    name = "google_trends"
    default_weight = 0.6

    def __init__(self, weight: float = 0.6):
        self.default_weight = weight
        self._pytrends = None
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            from pytrends.request import TrendReq
            self._pytrends = TrendReq(hl="en-US", tz=360, timeout=(5, 10))
            self._available = True
            return True
        except ImportError:
            logger.info("Google Trends: pytrends not installed — source disabled")
            self._available = False
            return False
        except Exception as e:
            logger.warning(f"Google Trends init failed: {e}")
            self._available = False
            return False

    async def search(self, query: str) -> list[ResearchResult]:
        if not self.is_available():
            return []

        try:
            import asyncio
            # pytrends is synchronous — run in thread pool
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, self._fetch_trends, query)
            return results
        except Exception as e:
            logger.warning(f"Google Trends search failed for '{query}': {e}")
            return []

    def _fetch_trends(self, query: str) -> list[ResearchResult]:
        """Fetch interest over time for the query. Returns synthetic text results."""
        # Clean query — take first 5 words max for Google Trends
        words = query.split()[:5]
        search_term = " ".join(words)

        try:
            self._pytrends.build_payload([search_term], cat=0, timeframe="now 7-d")
            interest = self._pytrends.interest_over_time()
        except Exception as e:
            logger.debug(f"Google Trends payload failed: {e}")
            return []

        if interest.empty or search_term not in interest.columns:
            return []

        # Get recent trend data
        values = interest[search_term].tolist()
        if not values:
            return []

        current = values[-1]
        avg = sum(values) / len(values)
        peak = max(values)

        # Detect trend direction
        if len(values) >= 3:
            recent = sum(values[-3:]) / 3
            older = sum(values[:3]) / 3
            if recent > older * 1.3:
                trend = "rising"
            elif recent < older * 0.7:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient data"

        text = (
            f"Google Trends: Search interest for '{search_term}' is {trend}. "
            f"Current: {current}/100, 7-day avg: {avg:.0f}/100, peak: {peak}/100."
        )

        return [ResearchResult(
            text=text,
            link=f"https://trends.google.com/trends/explore?q={search_term.replace(' ', '+')}",
            published=datetime.now(timezone.utc),
            source=self.name,
            weight=self.default_weight,
        )]
