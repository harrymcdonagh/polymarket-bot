from __future__ import annotations
import logging
import re
import time
import httpx
from src.research.structured_base import StructuredDataSource
from src.models import ScannedMarket

logger = logging.getLogger(__name__)
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"

ECONOMIC_KEYWORDS = re.compile(
    r"\binflation\b|\bcpi\b|\binterest rate\b|\bfed\b|\bfederal reserve\b|"
    r"\bunemployment\b|\brecession\b|\bgdp\b|\beconomy\b|\beconomic\b",
    re.IGNORECASE,
)

SERIES_IDS = {
    "CPIAUCSL": "fred_cpi_latest",
    "FEDFUNDS": "fred_fed_funds_rate",
    "UNRATE": "fred_unemployment",
}
CACHE_TTL = 21600  # 6 hours

class FREDSource(StructuredDataSource):
    """Fetches key economic indicators from FRED. Requires API key."""
    name = "fred"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._cache: dict[str, tuple[float, float]] = {}

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        if not ECONOMIC_KEYWORDS.search(market.question):
            return {"fred_cpi_latest": 0.0, "fred_fed_funds_rate": 0.0, "fred_unemployment": 0.0, "fred_is_relevant": 0.0}
        try:
            features: dict[str, float] = {}
            async with httpx.AsyncClient(timeout=10) as client:
                for series_id, feature_name in SERIES_IDS.items():
                    value = await self._fetch_series(client, series_id)
                    features[feature_name] = value
            features["fred_is_relevant"] = 1.0
            return features
        except Exception as e:
            logger.warning(f"FRED fetch failed: {e}")
            return {}

    async def _fetch_series(self, client: httpx.AsyncClient, series_id: str) -> float:
        now = time.time()
        if series_id in self._cache:
            cached_at, value = self._cache[series_id]
            if now - cached_at < CACHE_TTL:
                return value
        resp = await client.get(FRED_API_URL, params={
            "series_id": series_id, "api_key": self.api_key,
            "file_type": "json", "sort_order": "desc", "limit": 1,
        })
        if resp.status_code != 200:
            logger.warning(f"FRED API returned {resp.status_code} for {series_id}")
            return 0.0
        observations = resp.json().get("observations", [])
        if not observations:
            return 0.0
        try:
            value = float(observations[0].get("value", "0"))
        except (ValueError, TypeError):
            value = 0.0
        self._cache[series_id] = (now, value)
        return value
