from __future__ import annotations
import logging
from datetime import datetime, timezone
import httpx
from src.research.base import ResearchSource, ResearchResult

logger = logging.getLogger(__name__)
METACULUS_API = "https://www.metaculus.com/api/posts/"


class MetaculusSource(ResearchSource):
    """Fetches community forecasts from Metaculus via the v2 API.

    The v2 API has no text search — we fetch open binary questions with
    community predictions and do client-side keyword matching.
    """
    name = "metaculus"

    def __init__(self, weight: float = 0.9, api_token: str = ""):
        self.default_weight = weight
        self.api_token = api_token

    def is_available(self) -> bool:
        return bool(self.api_token)

    async def search(self, query: str) -> list[ResearchResult]:
        try:
            headers = {
                "Authorization": f"Token {self.api_token}",
                "User-Agent": "polymarket-bot/1.0 (research; +https://github.com)",
            }
            # Extract keywords for client-side matching (3+ char words)
            keywords = [w.lower() for w in query.split() if len(w) >= 3]
            if not keywords:
                return []

            async with httpx.AsyncClient(timeout=15, headers=headers) as client:
                resp = await client.get(METACULUS_API, params={
                    "statuses": "open",
                    "forecast_type": "binary",
                    "with_cp": "true",
                    "order_by": "-hotness",
                    "limit": 50,
                })
                if resp.status_code != 200:
                    logger.warning(f"Metaculus API returned {resp.status_code}")
                    return []
                data = resp.json()
                posts = data.get("results", [])

            results = []
            for post in posts:
                title = post.get("title", "")
                title_lower = title.lower()
                # Match if at least 2 keywords hit, or 1 if query is short
                min_hits = min(2, len(keywords))
                hits = sum(1 for kw in keywords if kw in title_lower)
                if hits < min_hits:
                    continue

                # Extract community prediction from aggregations
                question = post.get("question")
                if not question:
                    continue
                aggregations = question.get("aggregations", {})
                rw = aggregations.get("recency_weighted", {})
                latest = rw.get("latest")
                if not latest:
                    continue
                centers = latest.get("centers", [])
                if not centers:
                    continue

                median = centers[0]
                forecaster_count = latest.get("forecaster_count", 0)
                pct = round(median * 100)
                slug = post.get("slug", "")
                post_id = post.get("id", "")
                link = f"https://www.metaculus.com/questions/{post_id}/{slug}/" if slug else ""
                text = f"Metaculus community predicts {pct}% likelihood ({forecaster_count} forecasters): {title}"
                results.append(ResearchResult(
                    text=text, link=link,
                    published=datetime.now(timezone.utc),
                    source="metaculus", weight=self.default_weight,
                ))
            return results
        except Exception as e:
            logger.warning(f"Metaculus search failed: {e}")
            return []
