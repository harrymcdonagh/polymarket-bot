import logging
import time
from newsapi import NewsApiClient
from src.research.base import ResearchSource, ResearchResult, parse_published

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 900  # 15 minutes


class NewsAPISource(ResearchSource):
    name = "newsapi"

    def __init__(self, api_key: str, weight: float = 1.0):
        self.default_weight = weight
        self._api_key = api_key
        self._client = NewsApiClient(api_key=api_key) if api_key else None
        self._cache: dict[str, tuple[float, list[ResearchResult]]] = {}

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str) -> list[ResearchResult]:
        if not self.is_available():
            return []

        now = time.time()
        if query in self._cache:
            cached_at, results = self._cache[query]
            if now - cached_at < CACHE_TTL_SECONDS:
                return results

        try:
            response = self._client.get_top_headlines(q=query, language="en", page_size=100)
            results = []
            for article in response.get("articles", []):
                title = article.get("title")
                if not title:
                    continue
                desc = article.get("description") or ""
                results.append(ResearchResult(
                    text=f"{title}. {desc}" if desc else title,
                    link=article.get("url", ""),
                    published=parse_published(article.get("publishedAt", "")),
                    source=self.name,
                    weight=self.default_weight,
                ))
            self._cache[query] = (now, results)
            return results
        except Exception as e:
            logger.warning(f"NewsAPI search failed for '{query}': {e}")
            return []
