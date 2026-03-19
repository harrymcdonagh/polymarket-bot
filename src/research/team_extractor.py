from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)

BALLDONTLIE_BASE = "https://api.balldontlie.io/v1"

EXTRACTION_PROMPT = """Extract the sport and two team names from this prediction market question.
Return JSON: {"sport": "<nba|nhl|nfl|mlb>", "team_a": "<full team name for YES side>", "team_b": "<full team name>"}
Return null if this is not a team sports matchup (e.g., crypto, politics, tennis, esports).
team_a should be the first-mentioned team (typically the YES side).
Normalize nicknames to full names (e.g., "Raps" -> "Toronto Raptors").
Only return JSON, no other text."""


@dataclass(frozen=True)
class TeamInfo:
    sport: str
    team_a: str
    team_b: str


class TeamExtractor:
    """Extracts sport/team info from market questions using LLM. Caches results."""

    def __init__(self, anthropic_key: str = "", model: str = "claude-haiku-4-5-20251001"):
        self._api_key = anthropic_key
        self._model = model
        self._cache: dict[str, TeamInfo | None] = {}
        self._team_lists: dict[str, list[dict]] = {}  # sport -> [{id, full_name}, ...]

    async def extract(self, question: str) -> TeamInfo | None:
        """Extract sport and team names from a market question. Cached per question."""
        if question in self._cache:
            return self._cache[question]

        if not self._api_key:
            self._cache[question] = None
            return None

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)
            response = client.messages.create(
                model=self._model,
                max_tokens=150,
                messages=[{"role": "user", "content": f"{EXTRACTION_PROMPT}\n\nQuestion: {question}"}],
            )
            text = response.content[0].text.strip()
            # Strip markdown code fences if present
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            text = text.strip()
            parsed = json.loads(text)
            if parsed is None:
                self._cache[question] = None
                return None
            info = TeamInfo(
                sport=parsed["sport"].lower(),
                team_a=parsed["team_a"],
                team_b=parsed["team_b"],
            )
            self._cache[question] = info
            return info
        except Exception as e:
            logger.warning(f"Team extraction failed for '{question[:60]}': {e}")
            self._cache[question] = None
            return None

    async def resolve_team_ids(self, info: TeamInfo, bdl_api_key: str) -> tuple[int | None, int | None]:
        """Resolve team names to BALLDONTLIE IDs. Caches team lists per sport."""
        teams = await self._get_team_list(info.sport, bdl_api_key)
        if not teams:
            return None, None
        id_a = self._fuzzy_match(info.team_a, teams)
        id_b = self._fuzzy_match(info.team_b, teams)
        return id_a, id_b

    async def _get_team_list(self, sport: str, api_key: str) -> list[dict]:
        """Fetch and cache team list from BALLDONTLIE."""
        if sport in self._team_lists:
            return self._team_lists[sport]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BALLDONTLIE_BASE}/{sport}/teams",
                    headers={"Authorization": api_key},
                )
                if resp.status_code != 200:
                    logger.warning(f"BALLDONTLIE teams API returned {resp.status_code} for {sport}")
                    return []
                data = resp.json().get("data", [])
                self._team_lists[sport] = data
                return data
        except Exception as e:
            logger.warning(f"Failed to fetch {sport} team list: {e}")
            return []

    def _fuzzy_match(self, name: str, teams: list[dict]) -> int | None:
        """Match a team name against the BALLDONTLIE team list."""
        name_lower = name.lower()
        # Exact match first
        for team in teams:
            if team["full_name"].lower() == name_lower:
                return team["id"]
        # Partial match (nickname or city)
        for team in teams:
            full = team["full_name"].lower()
            if name_lower in full or full in name_lower:
                return team["id"]
        # Last word match (e.g., "Lakers" matches "Los Angeles Lakers")
        for team in teams:
            if team["full_name"].lower().endswith(name_lower):
                return team["id"]
        logger.warning(f"Could not match team '{name}' in BALLDONTLIE")
        return None
