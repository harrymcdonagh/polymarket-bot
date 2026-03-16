from __future__ import annotations
import logging
from datetime import datetime, timezone
import httpx
from src.research.base import ResearchSource, ResearchResult

logger = logging.getLogger(__name__)
METACULUS_API = "https://www.metaculus.com/api2/questions/"

class MetaculusSource(ResearchSource):
    """Fetches community forecasts from Metaculus superforecasters."""
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
            async with httpx.AsyncClient(timeout=10, headers=headers) as client:
                resp = await client.get(METACULUS_API, params={
                    "search": query,
                    "status": "open",
                    "type": "forecast",
                    "limit": 5,
                    "order_by": "-activity",
                })
                if resp.status_code != 200:
                    logger.warning(f"Metaculus API returned {resp.status_code}")
                    return []
                data = resp.json()
                questions = data.get("results", [])
            results = []
            for q in questions:
                community = q.get("community_prediction", {})
                median = None
                if isinstance(community, dict):
                    full = community.get("full", {})
                    if isinstance(full, dict):
                        median = full.get("q2")
                if median is None:
                    continue
                forecasters = q.get("number_of_forecasters", 0)
                title = q.get("title", "Unknown")
                pct = round(median * 100)
                page_url = q.get("page_url", "")
                link = f"https://www.metaculus.com{page_url}" if page_url else ""
                text = f"Metaculus community predicts {pct}% likelihood ({forecasters} forecasters): {title}"
                results.append(ResearchResult(text=text, link=link, published=datetime.now(timezone.utc), source="metaculus", weight=self.default_weight))
            return results
        except Exception as e:
            logger.warning(f"Metaculus search failed: {e}")
            return []
