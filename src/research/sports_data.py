from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
import httpx
from src.research.structured_base import StructuredDataSource
from src.research.team_extractor import TeamExtractor
from src.models import ScannedMarket

logger = logging.getLogger(__name__)

BALLDONTLIE_BASE = "https://api.balldontlie.io/v1"
DEFAULTS = {"rest_days_differential": 0.0, "standings_pct_delta": 0.0, "sports_is_relevant": 0.0}


class SportsDataSource(StructuredDataSource):
    """Fetches rest-day differential and standings delta from BALLDONTLIE."""
    name = "sports_data"

    def __init__(self, api_key: str = "", team_extractor: TeamExtractor | None = None):
        self.api_key = api_key
        self.extractor = team_extractor or TeamExtractor()

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        info = await self.extractor.extract(market.question)
        if info is None:
            return dict(DEFAULTS)

        try:
            id_a, id_b = await self.extractor.resolve_team_ids(info, self.api_key)
            if id_a is None or id_b is None:
                return dict(DEFAULTS)

            async with httpx.AsyncClient(timeout=10) as client:
                rest_diff = await self._get_rest_differential(client, info.sport, id_a, id_b)
                standings_delta = await self._get_standings_delta(client, info.sport, id_a, id_b)

            return {
                "rest_days_differential": rest_diff,
                "standings_pct_delta": standings_delta,
                "sports_is_relevant": 1.0,
            }
        except Exception as e:
            logger.warning(f"SportsDataSource failed for '{market.question[:60]}': {e}")
            return {}

    async def _get_rest_differential(self, client: httpx.AsyncClient,
                                      sport: str, id_a: int, id_b: int) -> float:
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=7)).isoformat()
        end = (today - timedelta(days=1)).isoformat()

        rest_a = await self._days_since_last_game(client, sport, id_a, start, end, today)
        rest_b = await self._days_since_last_game(client, sport, id_b, start, end, today)
        return float(rest_a - rest_b)

    async def _days_since_last_game(self, client: httpx.AsyncClient,
                                     sport: str, team_id: int,
                                     start: str, end: str, today) -> int:
        resp = await client.get(
            f"{BALLDONTLIE_BASE}/{sport}/games",
            headers={"Authorization": self.api_key},
            params={"team_ids[]": team_id, "start_date": start, "end_date": end},
        )
        if resp.status_code != 200:
            return 3
        games = resp.json().get("data", [])
        if not games:
            return 3
        last_date_str = games[-1].get("date", "")[:10]
        try:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            return (today - last_date).days
        except ValueError:
            return 3

    async def _get_standings_delta(self, client: httpx.AsyncClient,
                                    sport: str, id_a: int, id_b: int) -> float:
        resp = await client.get(
            f"{BALLDONTLIE_BASE}/{sport}/standings",
            headers={"Authorization": self.api_key},
        )
        if resp.status_code != 200:
            return 0.0
        standings = resp.json().get("data", [])
        pct_a = self._find_win_pct(standings, id_a)
        pct_b = self._find_win_pct(standings, id_b)
        if pct_a is None or pct_b is None:
            return 0.0
        return round(pct_a - pct_b, 4)

    def _find_win_pct(self, standings: list[dict], team_id: int) -> float | None:
        for entry in standings:
            tid = entry.get("team", {}).get("id")
            if tid == team_id:
                wins = entry.get("wins", 0)
                losses = entry.get("losses", 0)
                total = wins + losses
                return wins / total if total > 0 else 0.0
        return None
