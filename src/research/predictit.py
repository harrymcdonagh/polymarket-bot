from __future__ import annotations
import logging
from datetime import datetime, timezone
import httpx
from src.research.base import ResearchSource, ResearchResult

logger = logging.getLogger(__name__)
MANIFOLD_SEARCH_URL = "https://api.manifold.markets/v0/search-markets"

class PredictItSource(ResearchSource):
    """Fetches prediction market prices from Manifold Markets for cross-reference.
    Named PredictIt for historical reasons; uses Manifold Markets API since PredictIt shut down in 2023."""
    name = "predictit"

    def __init__(self, weight: float = 0.85):
        self.default_weight = weight

    def is_available(self) -> bool:
        return True

    async def search(self, query: str) -> list[ResearchResult]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(MANIFOLD_SEARCH_URL, params={"term": query, "limit": 5})
                if resp.status_code != 200:
                    logger.warning(f"Manifold API returned {resp.status_code}")
                    return []
                markets = resp.json()
            results = []
            for m in markets[:3]:
                question = m.get("question", "")
                prob = m.get("probability")
                if prob is None:
                    continue
                pct = round(prob * 100)
                bettors = m.get("uniqueBettorCount", 0)
                url = m.get("url", "")
                text = f"Manifold Markets prices this at {pct}% YES ({bettors} traders): {question}"
                results.append(ResearchResult(text=text, link=url, published=datetime.now(timezone.utc), source="predictit", weight=self.default_weight))
            return results
        except Exception as e:
            logger.warning(f"PredictIt/Manifold search failed: {e}")
            return []
