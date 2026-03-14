import json
import httpx
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.models import ScannedMarket, ScanFlag

logger = logging.getLogger(__name__)


class MarketScanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gamma_url = settings.POLYMARKET_GAMMA_URL
        self.clob_url = settings.POLYMARKET_CLOB_URL

    async def scan(self) -> list[ScannedMarket]:
        """Fetch active markets from Gamma API, filter and flag."""
        raw_markets = await self._fetch_all_active_markets()
        logger.info(f"Fetched {len(raw_markets)} active markets")

        results = []
        for market in raw_markets:
            if not self._passes_filters(market):
                continue

            # Parse outcome prices from JSON string
            try:
                prices = json.loads(market.get("outcomePrices", "[]"))
                token_ids = json.loads(market.get("clobTokenIds", "[]"))
            except (json.JSONDecodeError, TypeError):
                continue

            if len(prices) < 2 or len(token_ids) < 2:
                continue

            yes_price = float(prices[0])
            no_price = float(prices[1])
            spread = abs(1.0 - yes_price - no_price)

            flags = self._detect_flags(market, spread=spread)

            end_date = None
            days_to_res = None
            end_date_str = market.get("endDateIso") or market.get("end_date_iso")
            if end_date_str:
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    days_to_res = (end_date - datetime.now(timezone.utc)).days
                except (ValueError, TypeError):
                    pass

            results.append(ScannedMarket(
                condition_id=market.get("conditionId") or market.get("condition_id", ""),
                question=market.get("question", ""),
                slug=market.get("slug", ""),
                token_yes_id=token_ids[0],
                token_no_id=token_ids[1],
                yes_price=yes_price,
                no_price=no_price,
                spread=spread,
                liquidity=float(market.get("liquidityNum", 0) or market.get("liquidity", 0)),
                volume_24h=float(market.get("volume24hr", 0)),
                end_date=end_date,
                days_to_resolution=days_to_res,
                flags=flags,
                scanned_at=datetime.now(timezone.utc),
            ))

        # Sort by number of flags (most interesting first), then by volume
        results.sort(key=lambda m: (-len(m.flags), -m.volume_24h))
        logger.info(f"Scanner found {len(results)} markets passing filters, {sum(1 for m in results if m.flags)} flagged")
        return results

    async def _fetch_all_active_markets(self, max_markets: int = 5000) -> list[dict]:
        """Paginate through Gamma API to get active, non-closed markets."""
        all_markets = []
        offset = 0
        limit = 100
        async with httpx.AsyncClient(timeout=30) as client:
            while len(all_markets) < max_markets:
                resp = await client.get(
                    f"{self.gamma_url}/markets",
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": limit,
                        "offset": offset,
                        "order": "volume24hr",
                        "ascending": "false",
                    },
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                all_markets.extend(batch)
                if len(batch) < limit:
                    break
                offset += limit
        logger.info(f"Fetched {len(all_markets)} markets (cap: {max_markets})")
        return all_markets[:max_markets]

    def _passes_filters(self, market: dict) -> bool:
        """Check if market meets minimum liquidity, volume, and time criteria."""
        liquidity = float(market.get("liquidityNum", 0) or market.get("liquidity", 0))
        volume = float(market.get("volume24hr", 0))

        if liquidity < self.settings.MIN_LIQUIDITY:
            return False
        if volume < self.settings.MIN_VOLUME_24H:
            return False

        # Check time to resolution
        end_date_str = market.get("endDateIso") or market.get("end_date_iso")
        if end_date_str:
            try:
                end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                days = (end - datetime.now(timezone.utc)).days
                if days > self.settings.MAX_DAYS_TO_RESOLUTION:
                    return False
                if days < 0:
                    return False
            except (ValueError, TypeError):
                pass

        return True

    def _detect_flags(self, market: dict, spread: float) -> list[ScanFlag]:
        """Detect anomalies worth investigating."""
        flags = []

        if spread >= self.settings.SPREAD_ALERT_THRESHOLD:
            flags.append(ScanFlag.WIDE_SPREAD)

        volume = float(market.get("volume24hr", 0))
        if volume > 50000:
            flags.append(ScanFlag.HIGH_VOLUME)

        return flags
