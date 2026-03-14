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
