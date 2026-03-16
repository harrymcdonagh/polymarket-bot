from __future__ import annotations
import logging
import httpx
from src.research.structured_base import StructuredDataSource
from src.models import ScannedMarket

logger = logging.getLogger(__name__)
CLOB_BOOK_URL = "https://clob.polymarket.com/book"

class CLOBSource(StructuredDataSource):
    """Fetches real-time order book depth from Polymarket CLOB REST API."""
    name = "clob"

    def is_available(self) -> bool:
        return True

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(CLOB_BOOK_URL, params={"token_id": market.token_yes_id})
                if resp.status_code != 200:
                    logger.warning(f"CLOB API returned {resp.status_code}")
                    return {}
                book = resp.json()
                return self._extract_features(book, market.yes_price)
        except Exception as e:
            logger.warning(f"CLOB fetch failed: {e}")
            return {}

    def _extract_features(self, book: dict, gamma_price: float) -> dict[str, float]:
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if not bids or not asks:
            return {}
        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])
        midpoint = (best_bid + best_ask) / 2
        buy_depth = sum(float(b["size"]) for b in bids if float(b["price"]) >= midpoint * 0.95)
        sell_depth = sum(float(a["size"]) for a in asks if float(a["price"]) <= midpoint * 1.05)
        total_depth = buy_depth + sell_depth
        imbalance = buy_depth / total_depth if total_depth > 0 else 0.5
        return {
            "clob_bid_ask_spread": best_ask - best_bid,
            "clob_buy_depth": buy_depth,
            "clob_sell_depth": sell_depth,
            "clob_imbalance": imbalance,
            "clob_midpoint_vs_gamma": midpoint - gamma_price,
        }
