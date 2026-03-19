from __future__ import annotations
import logging
from datetime import datetime, timezone
import httpx
from src.research.structured_base import StructuredDataSource
from src.research.team_extractor import TeamExtractor
from src.models import ScannedMarket

logger = logging.getLogger(__name__)

ODDSPAPI_BASE = "https://api.oddspapi.com/v1"
MONTHLY_BUDGET = 220  # leave buffer from 250 limit

# Map BALLDONTLIE sport names to OddsPapi sport keys
SPORT_MAP = {
    "nba": "basketball_nba",
    "nhl": "icehockey_nhl",
    "nfl": "americanfootball_nfl",
    "mlb": "baseball_mlb",
}


class OddsDataSource(StructuredDataSource):
    """Fetches sharp-book odds from OddsPapi for CLV calculation."""
    name = "odds_data"

    def __init__(self, api_key: str = "", team_extractor: TeamExtractor | None = None):
        self.api_key = api_key
        self.extractor = team_extractor or TeamExtractor()
        self._monthly_count = 0
        self._month_key = datetime.now(timezone.utc).strftime("%Y-%m")  # reset counter when month changes

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        info = await self.extractor.extract(market.question)
        if info is None:
            return {"sharp_implied_prob": 0.0}

        sport_key = SPORT_MAP.get(info.sport)
        if not sport_key:
            return {"sharp_implied_prob": 0.0}

        # Budget tracking — reset monthly
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        if self._month_key != current_month:
            self._monthly_count = 0
            self._month_key = current_month

        if self._monthly_count >= MONTHLY_BUDGET:
            logger.warning(f"OddsPapi monthly budget exhausted ({self._monthly_count}/{MONTHLY_BUDGET})")
            return {"sharp_implied_prob": 0.0}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{ODDSPAPI_BASE}/odds",
                    params={"sport": sport_key, "apiKey": self.api_key,
                            "regions": "eu", "markets": "h2h",
                            "bookmakers": "pinnacle"},
                )
                self._monthly_count += 1

                if resp.status_code != 200:
                    logger.warning(f"OddsPapi returned {resp.status_code}")
                    return {}

                data = resp.json().get("data", [])
                prob = self._find_sharp_prob(data, info.team_a)
                return {"sharp_implied_prob": prob}

        except Exception as e:
            logger.warning(f"OddsDataSource failed for '{market.question[:60]}': {e}")
            return {}

    def _find_sharp_prob(self, events: list[dict], team_a: str) -> float:
        team_lower = team_a.lower()
        for event in events:
            for bookmaker in event.get("bookmakers", []):
                if bookmaker.get("key") != "pinnacle":
                    continue
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        if team_lower in outcome.get("name", "").lower():
                            price = outcome.get("price", 0)
                            if price > 0:
                                return round(1.0 / price, 4)
        return 0.0
