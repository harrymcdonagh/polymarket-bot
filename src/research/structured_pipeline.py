from __future__ import annotations
import asyncio
import logging
from src.research.structured_base import StructuredDataSource
from src.models import ScannedMarket

logger = logging.getLogger(__name__)

class StructuredDataPipeline:
    """Orchestrates structured data sources in parallel, merges feature dicts."""
    def __init__(self, sources: list[StructuredDataSource], timeout: float = 10.0):
        self.sources = sources
        self.timeout = timeout

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        available = [s for s in self.sources if s.is_available()]
        if not available:
            return {}
        tasks = [self._fetch_with_timeout(s, market) for s in available]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged: dict[str, float] = {}
        for source, result in zip(available, results):
            if isinstance(result, Exception):
                logger.warning(f"Structured source '{source.name}' failed: {result}")
                continue
            merged.update(result)
        return merged

    async def _fetch_with_timeout(self, source: StructuredDataSource, market: ScannedMarket) -> dict[str, float]:
        try:
            return await asyncio.wait_for(source.fetch(market), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Structured source '{source.name}' timed out after {self.timeout}s")
            return {}
