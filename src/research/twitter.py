import logging
from twscrape import API

logger = logging.getLogger(__name__)


class TwitterResearcher:
    def __init__(self, api: API | None = None):
        self.api = api or API()

    async def search(self, query: str, limit: int = 50) -> list[dict]:
        """Search Twitter for tweets related to a query."""
        results = []
        try:
            async for tweet in self.api.search(query, limit=limit):
                results.append({
                    "text": tweet.rawContent,
                    "date": str(tweet.date),
                    "likes": tweet.likeCount,
                    "source": "twitter",
                })
        except Exception as e:
            logger.warning(f"Twitter search failed for '{query}': {e}")
        return results


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
            # Verify we actually have pool accounts by checking the pool
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # If we're in an event loop, defer the check to search time
                self._checked_available = True
            except RuntimeError:
                # No running loop — can do sync check
                pool = asyncio.run(self._api.pool.get_all())
                if not pool:
                    logger.warning("Twitter: no accounts in twscrape pool — source disabled")
                    self._checked_available = False
                    return False
                self._checked_available = True
            return True
        except Exception as e:
            logger.warning(f"Twitter source unavailable: {e}")
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
