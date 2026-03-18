import json
import logging
import re
import time
import httpx

logger = logging.getLogger(__name__)


class CryptoScanner:
    """Find active 5-minute BTC/ETH markets on Polymarket."""

    def __init__(self, gamma_url: str = "https://gamma-api.polymarket.com"):
        self.gamma_url = gamma_url
        self._cache: dict | None = None
        self._cache_ts: float = 0
        self._cache_ttl: float = 60  # seconds

    async def find_active_5min_market(self, symbol: str = "BTC") -> dict | None:
        """Query Gamma API for current active 5-minute market.
        Returns: {market_id, token_id, strike_price, yes_price, no_price, end_time, question}
        or None if no active market found.
        """
        now = time.time()
        if self._cache is not None and now - self._cache_ts < self._cache_ttl:
            return self._cache

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.gamma_url}/markets",
                    params={"tag": "crypto", "closed": "false", "limit": 50},
                )
                if resp.status_code != 200:
                    logger.warning(f"Gamma API returned {resp.status_code}")
                    return None
                markets = resp.json()
                if not isinstance(markets, list):
                    return None

                for m in markets:
                    question = m.get("question", "")
                    if symbol.upper() not in question.upper():
                        continue
                    if not self._is_5min_market(m):
                        continue
                    if m.get("closed", False):
                        continue

                    tokens = m.get("tokens", [])
                    token_id = None
                    for tok in tokens:
                        if tok.get("outcome", "").lower() == "yes":
                            token_id = tok.get("token_id")
                            break
                    if not token_id:
                        continue

                    try:
                        prices = json.loads(m.get("outcomePrices", "[]"))
                        yes_price = float(prices[0]) if len(prices) >= 1 else 0.5
                        no_price = float(prices[1]) if len(prices) >= 2 else 0.5
                    except (json.JSONDecodeError, ValueError, IndexError):
                        yes_price = no_price = 0.5

                    result = {
                        "market_id": m.get("conditionId", ""),
                        "token_id": token_id,
                        "strike_price": self._extract_strike(question),
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "end_time": m.get("endDate", ""),
                        "question": question,
                    }
                    self._cache = result
                    self._cache_ts = now
                    return result
                return None
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            return None

    async def check_resolution(self, condition_id: str, token_id: str | None = None) -> str | None:
        """Check if a market has resolved. Uses clob_token_ids (not condition_id — Gamma ignores it).
        Returns 'YES'/'NO' or None."""
        if not token_id:
            if self._cache and self._cache.get("market_id") == condition_id:
                token_id = self._cache.get("token_id")
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
                    yes_price = float(prices[0])
                    if yes_price > 0.5:
                        return "YES"
                    elif yes_price < 0.5:
                        return "NO"
        except Exception as e:
            logger.debug(f"Resolution check error: {e}")
        return None

    def _is_5min_market(self, market: dict) -> bool:
        question = market.get("question", "").lower()
        if "5 min" in question or "5-min" in question:
            return True
        if re.search(r"at \d{1,2}:\d{2}", question):
            return True
        return False

    def _extract_strike(self, question: str) -> float | None:
        match = re.search(r'\$([0-9,]+(?:\.\d+)?)', question)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                pass
        return None
