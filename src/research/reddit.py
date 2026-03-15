import logging
import praw
from src.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = ["polymarket", "prediction_market", "wallstreetbets", "news", "worldnews"]


class RedditResearcher:
    def __init__(self, reddit: praw.Reddit | None = None, settings: Settings | None = None):
        if reddit:
            self.reddit = reddit
        else:
            s = settings or Settings()
            self.reddit = praw.Reddit(
                client_id=s.REDDIT_CLIENT_ID,
                client_secret=s.REDDIT_CLIENT_SECRET,
                user_agent=s.REDDIT_USER_AGENT,
            )

    def search(self, query: str, subreddits: list[str] | None = None, limit: int = 30) -> list[dict]:
        """Search Reddit for posts related to a query."""
        subs = subreddits or DEFAULT_SUBREDDITS
        results = []
        for sub_name in subs:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                for post in subreddit.search(query, sort="relevance", time_filter="week", limit=limit):
                    results.append({
                        "text": f"{post.title}. {post.selftext[:500]}",
                        "score": post.score,
                        "comments": post.num_comments,
                        "subreddit": sub_name,
                        "source": "reddit",
                    })
            except Exception as e:
                logger.warning(f"Reddit search failed for r/{sub_name}: {e}")
        return results


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
