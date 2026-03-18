import json
import logging
import time
import httpx

logger = logging.getLogger(__name__)


class CryptoScanner:
    """Find active 5-minute BTC Up/Down markets on Polymarket.

    Markets use deterministic slugs: btc-updown-5m-{unix_timestamp}
    where timestamp is the start of the 5-min window (aligned to 300s).
    Outcomes are "Up" / "Down" (not YES/NO).
    """

    def __init__(self, gamma_url: str = "https://gamma-api.polymarket.com"):
        self.gamma_url = gamma_url
        self._cache: dict | None = None
        self._cache_ts: float = 0
        self._cache_ttl: float = 60  # seconds

    def _current_window_slug(self, symbol: str = "BTC") -> str:
        """Compute the slug for the current 5-min window."""
        now = int(time.time())
        window_start = now - (now % 300)
        prefix = symbol.lower()
        return f"{prefix}-updown-5m-{window_start}"

    def _next_window_slug(self, symbol: str = "BTC") -> str:
        """Compute the slug for the next 5-min window."""
        now = int(time.time())
        window_start = now - (now % 300) + 300
        prefix = symbol.lower()
        return f"{prefix}-updown-5m-{window_start}"

    async def find_active_5min_market(self, symbol: str = "BTC") -> dict | None:
        """Find the current or next active 5-min market by computed slug.

        Returns: {market_id, token_up, token_down, up_price, down_price, end_time, question, slug}
        or None if no market found.
        """
        now = time.time()
        if self._cache is not None and now - self._cache_ts < self._cache_ttl:
            return self._cache

        # Try current window first, then next window
        for slug in [self._current_window_slug(symbol), self._next_window_slug(symbol)]:
            result = await self._fetch_by_slug(slug)
            if result is not None:
                self._cache = result
                self._cache_ts = now
                return result

        logger.debug(f"No active 5-min market found for {symbol}")
        return None

    async def _fetch_by_slug(self, slug: str) -> dict | None:
        """Fetch a market event by its slug."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.gamma_url}/events",
                    params={"slug": slug},
                )
                if resp.status_code != 200:
                    return None
                events = resp.json()
                if not isinstance(events, list) or not events:
                    return None

                event = events[0]
                markets = event.get("markets", [])
                if not markets:
                    return None

                m = markets[0]
                if m.get("closed", False):
                    return None

                # Parse token IDs — outcomes are ["Up", "Down"]
                clob_ids = json.loads(m.get("clobTokenIds", "[]"))
                token_up = clob_ids[0] if len(clob_ids) >= 1 else None
                token_down = clob_ids[1] if len(clob_ids) >= 2 else None
                if not token_up:
                    return None

                # Parse prices — [up_price, down_price]
                try:
                    prices = json.loads(m.get("outcomePrices", "[]"))
                    up_price = float(prices[0]) if len(prices) >= 1 else 0.5
                    down_price = float(prices[1]) if len(prices) >= 2 else 0.5
                except (json.JSONDecodeError, ValueError, IndexError):
                    up_price = down_price = 0.5

                return {
                    "market_id": m.get("conditionId", ""),
                    "token_up": token_up,
                    "token_down": token_down,
                    "up_price": up_price,
                    "down_price": down_price,
                    "end_time": m.get("endDate", ""),
                    "question": m.get("question", ""),
                    "slug": slug,
                }
        except Exception as e:
            logger.error(f"Scanner fetch error for {slug}: {e}")
            return None

    async def check_resolution(self, condition_id: str, token_id: str | None = None) -> str | None:
        """Check if a market has resolved. Returns 'Up'/'Down' or None.

        Uses clob_token_ids for lookup (Gamma API ignores conditionId param).
        """
        if not token_id:
            if self._cache and self._cache.get("market_id") == condition_id:
                token_id = self._cache.get("token_up")
            if not token_id:
                return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.gamma_url}/markets",
                    params={"clob_token_ids": token_id, "limit": 1},
                )
                if resp.status_code != 200:
                    return None
                markets = resp.json()
                if not isinstance(markets, list) or not markets:
                    return None
                data = markets[0]
                if not data.get("resolved") and not data.get("closed"):
                    return None
                prices = json.loads(data.get("outcomePrices", "[]"))
                if len(prices) >= 2:
                    up_price = float(prices[0])
                    if up_price > 0.5:
                        return "Up"
                    elif up_price < 0.5:
                        return "Down"
        except Exception as e:
            logger.debug(f"Resolution check error: {e}")
        return None
