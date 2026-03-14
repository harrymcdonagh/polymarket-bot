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
