from __future__ import annotations

import asyncio
import logging
from difflib import SequenceMatcher

from src.research.base import ResearchSource, ResearchResult
from src.research.sentiment import SentimentAnalyzer

logger = logging.getLogger(__name__)


def deduplicate(results: list[ResearchResult], threshold: float = 0.85) -> list[ResearchResult]:
    """Remove near-duplicate results, keeping the one with highest weight."""
    if not results:
        return []
    kept: list[ResearchResult] = []
    for result in results:
        is_dup = False
        for i, existing in enumerate(kept):
            ratio = SequenceMatcher(None, result.text.lower(), existing.text.lower()).ratio()
            if ratio >= threshold:
                if result.weight > existing.weight:
                    kept[i] = result
                is_dup = True
                break
        if not is_dup:
            kept.append(result)
    return kept


class ResearchPipeline:
    """Orchestrates research across all available sources with weighted aggregation."""

    def __init__(
        self,
        sources: list[ResearchSource],
        timeout: float = 10.0,
        sentiment_analyzer: SentimentAnalyzer | None = None,
    ):
        self.sources = sources
        self.timeout = timeout
        self.sentiment = sentiment_analyzer or SentimentAnalyzer(use_transformer=False)

    async def search(self, query: str) -> list[ResearchResult]:
        """Fan out query to all available sources, deduplicate results."""
        available = [s for s in self.sources if s.is_available()]
        if not available:
            logger.warning("No research sources available")
            return []

        tasks = []
        source_names = []
        for source in available:
            tasks.append(self._search_with_timeout(source, query))
            source_names.append(source.name)

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[ResearchResult] = []
        for name, result in zip(source_names, raw_results):
            if isinstance(result, Exception):
                logger.warning(f"Source '{name}' failed: {result}")
                continue
            all_results.extend(result)

        deduped = deduplicate(all_results, threshold=0.9)
        if not all_results and available:
            logger.error(f"All {len(available)} research sources returned zero results for '{query[:60]}' — predictions will lack sentiment data")
        else:
            logger.info(f"Research: {len(all_results)} results from {len(available)} sources, {len(deduped)} after dedup")
        return deduped

    async def search_and_analyze(self, query: str) -> dict:
        """Search all sources and return weighted sentiment analysis."""
        results = await self.search(query)
        if not results:
            return {
                "positive_ratio": 0, "negative_ratio": 0, "neutral_ratio": 0,
                "weighted_avg_score": 0, "sample_size": 0, "source_breakdown": {},
            }

        texts = [r.text for r in results]
        sentiments = self.sentiment.analyze_batch(texts)

        # Weighted aggregation
        total_weight = 0
        weighted_score = 0
        pos_weight = 0
        neg_weight = 0
        neu_weight = 0
        source_breakdown: dict[str, dict] = {}

        for result, sent in zip(results, sentiments):
            w = result.weight
            total_weight += w
            weighted_score += sent["score"] * w

            if sent["label"] == "positive":
                pos_weight += w
            elif sent["label"] == "negative":
                neg_weight += w
            else:
                neu_weight += w

            # Track per-source stats
            src = result.source
            if src not in source_breakdown:
                source_breakdown[src] = {"count": 0, "total_score": 0, "pos": 0, "neg": 0, "neu": 0}
            source_breakdown[src]["count"] += 1
            source_breakdown[src]["total_score"] += sent["score"]
            if sent["label"] == "positive":
                source_breakdown[src]["pos"] += 1
            elif sent["label"] == "negative":
                source_breakdown[src]["neg"] += 1
            else:
                source_breakdown[src]["neu"] += 1

        # Finalize source breakdown with per-source ratios
        for src in source_breakdown:
            count = source_breakdown[src]["count"]
            source_breakdown[src]["avg_score"] = source_breakdown[src].pop("total_score") / count
            source_breakdown[src]["positive_ratio"] = source_breakdown[src].pop("pos") / count
            source_breakdown[src]["negative_ratio"] = source_breakdown[src].pop("neg") / count
            source_breakdown[src]["neutral_ratio"] = source_breakdown[src].pop("neu") / count

        return {
            "positive_ratio": pos_weight / total_weight if total_weight else 0,
            "negative_ratio": neg_weight / total_weight if total_weight else 0,
            "neutral_ratio": neu_weight / total_weight if total_weight else 0,
            "weighted_avg_score": weighted_score / total_weight if total_weight else 0,
            "sample_size": len(results),
            "source_breakdown": source_breakdown,
        }

    async def _search_with_timeout(self, source: ResearchSource, query: str) -> list[ResearchResult]:
        try:
            return await asyncio.wait_for(source.search(query), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Source '{source.name}' timed out after {self.timeout}s")
            return []
