from __future__ import annotations
import logging
import time
import re
import httpx
from src.research.structured_base import StructuredDataSource
from src.models import ScannedMarket

logger = logging.getLogger(__name__)
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

CRYPTO_KEYWORDS: dict[str, str] = {
    r"\bbitcoin\b|\bbtc\b": "bitcoin",
    r"\bethereum\b|\beth\b": "ethereum",
    r"\bsolana\b|\bsol\b": "solana",
    r"\bdogecoin\b|\bdoge\b": "dogecoin",
    r"\bcardano\b|\bada\b": "cardano",
    r"\bripple\b|\bxrp\b": "ripple",
    r"\bpolygon\b|\bmatic\b": "matic-network",
}
CACHE_TTL = 300

class CoinGeckoSource(StructuredDataSource):
    """Fetches crypto prices from CoinGecko. Only activates for crypto markets."""
    name = "coingecko"

    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}

    def is_available(self) -> bool:
        return True

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        coin_id = self._detect_crypto(market.question)
        if not coin_id:
            return {"crypto_price_usd": 0.0, "crypto_24h_change": 0.0, "crypto_market_cap": 0.0, "crypto_is_relevant": 0.0}
        try:
            data = await self._fetch_price(coin_id)
            if not data:
                return {}
            return {
                "crypto_price_usd": data.get("usd", 0.0),
                "crypto_24h_change": data.get("usd_24h_change", 0.0),
                "crypto_market_cap": data.get("usd_market_cap", 0.0),
                "crypto_is_relevant": 1.0,
            }
        except Exception as e:
            logger.warning(f"CoinGecko fetch failed: {e}")
            return {}

    def _detect_crypto(self, question: str) -> str | None:
        q_lower = question.lower()
        if re.search(r"\bcrypto\b|\bcryptocurrency\b", q_lower):
            return "bitcoin"
        for pattern, coin_id in CRYPTO_KEYWORDS.items():
            if re.search(pattern, q_lower):
                return coin_id
        return None

    async def _fetch_price(self, coin_id: str) -> dict | None:
        now = time.time()
        if coin_id in self._cache:
            cached_at, data = self._cache[coin_id]
            if now - cached_at < CACHE_TTL:
                return data
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(COINGECKO_URL, params={
                "ids": coin_id, "vs_currencies": "usd",
                "include_24hr_change": "true", "include_market_cap": "true",
            })
            if resp.status_code != 200:
                logger.warning(f"CoinGecko API returned {resp.status_code}")
                return None
            data = resp.json().get(coin_id)
            if data:
                self._cache[coin_id] = (now, data)
            return data
