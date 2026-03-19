# External Sports Data Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rest-days differential, standings delta, and CLV features to the XGBoost model by integrating BALLDONTLIE and OddsPapi APIs.

**Architecture:** A shared `TeamExtractor` uses Haiku LLM to parse sport/team info from market questions (cached per question). Two new `StructuredDataSource` implementations — `SportsDataSource` (BALLDONTLIE) and `OddsDataSource` (OddsPapi) — consume the extractor and return numeric features. CLV delta is a diagnostic stored post-calibration, not an XGBoost input.

**Tech Stack:** Python 3.13, httpx, anthropic SDK (Haiku), BALLDONTLIE API, OddsPapi API, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-19-external-sports-data-features-design.md`

---

## File Map

**Create:**
| File | Responsibility |
|---|---|
| `src/research/team_extractor.py` | LLM-based sport/team extraction with caching + BALLDONTLIE team ID resolution |
| `src/research/sports_data.py` | `SportsDataSource` — schedule + standings from BALLDONTLIE |
| `src/research/odds_data.py` | `OddsDataSource` — sharp odds from OddsPapi |
| `tests/test_team_extractor.py` | Tests for team extraction and caching |
| `tests/test_sports_data.py` | Tests for SportsDataSource |
| `tests/test_odds_data.py` | Tests for OddsDataSource |

**Modify:**
| File | Change |
|---|---|
| `src/config.py` | Add `BALLDONTLIE_API_KEY` and `ODDSPAPI_API_KEY` settings |
| `src/pipeline.py:79-86` | Create TeamExtractor, pass to both new sources, add to StructuredDataPipeline; compute CLV post-calibration |
| `src/predictor/features.py:30-72` | Add 3 new features from structured_data dict |
| `src/predictor/xgb_model.py:7-24` | Add 3 features to FEATURE_ORDER |
| `src/predictor/trainer.py:69-105` | Add defaults for Gamma API fallback |
| `tests/test_predictor.py:94` | Update feature count assertion (37 → 40) |

---

### Task 1: Add API key settings to config

**Files:**
- Modify: `src/config.py:66-68`

- [ ] **Step 1: Add BALLDONTLIE and ODDSPAPI keys to Settings**

In `src/config.py`, after the FRED_API_KEY line (line 67), add:

```python
    # Sports data
    BALLDONTLIE_API_KEY: str = ""

    # Sharp odds
    ODDSPAPI_API_KEY: str = ""
```

- [ ] **Step 2: Verify config loads**

Run: `python -c "from src.config import Settings; s = Settings(); print(s.BALLDONTLIE_API_KEY, s.ODDSPAPI_API_KEY)"`
Expected: two empty strings printed

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat: add BALLDONTLIE_API_KEY and ODDSPAPI_API_KEY config settings"
```

---

### Task 2: Create TeamExtractor

**Files:**
- Create: `src/research/team_extractor.py`
- Create: `tests/test_team_extractor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_team_extractor.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.research.team_extractor import TeamExtractor, TeamInfo


@pytest.fixture
def extractor():
    return TeamExtractor(anthropic_key="test-key", model="claude-haiku-4-5-20251001")


def test_team_info_dataclass():
    info = TeamInfo(sport="nba", team_a="Toronto Raptors", team_b="Chicago Bulls")
    assert info.sport == "nba"
    assert info.team_a == "Toronto Raptors"
    assert info.team_b == "Chicago Bulls"


@pytest.mark.asyncio
async def test_extract_sports_market(extractor):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"sport": "nba", "team_a": "Toronto Raptors", "team_b": "Chicago Bulls"}')]
    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client
        result = await extractor.extract("Raptors vs. Bulls: O/U 234.5")
    assert result is not None
    assert result.sport == "nba"
    assert result.team_a == "Toronto Raptors"
    assert result.team_b == "Chicago Bulls"


@pytest.mark.asyncio
async def test_extract_non_sports_market(extractor):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='null')]
    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client
        result = await extractor.extract("Will Bitcoin reach $80,000?")
    assert result is None


@pytest.mark.asyncio
async def test_extract_caches_by_question(extractor):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"sport": "nba", "team_a": "Lakers", "team_b": "Celtics"}')]
    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client
        result1 = await extractor.extract("Lakers vs Celtics")
        result2 = await extractor.extract("Lakers vs Celtics")
    assert result1 == result2
    # LLM should only be called once
    mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_extract_handles_llm_error(extractor):
    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        mock_cls.return_value = mock_client
        result = await extractor.extract("Lakers vs Celtics")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_team_ids(extractor):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [
        {"id": 1, "full_name": "Toronto Raptors"},
        {"id": 2, "full_name": "Chicago Bulls"},
    ]}
    info = TeamInfo(sport="nba", team_a="Toronto Raptors", team_b="Chicago Bulls")
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        id_a, id_b = await extractor.resolve_team_ids(info, "test-bdl-key")
    assert id_a == 1
    assert id_b == 2


@pytest.mark.asyncio
async def test_resolve_team_ids_fuzzy_match(extractor):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [
        {"id": 10, "full_name": "Los Angeles Lakers"},
        {"id": 20, "full_name": "Boston Celtics"},
    ]}
    info = TeamInfo(sport="nba", team_a="Lakers", team_b="Celtics")
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        id_a, id_b = await extractor.resolve_team_ids(info, "test-bdl-key")
    assert id_a == 10
    assert id_b == 20
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_team_extractor.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement TeamExtractor**

Create `src/research/team_extractor.py`:

```python
from __future__ import annotations
import json
import logging
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_team_extractor.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/team_extractor.py tests/test_team_extractor.py
git commit -m "feat: add TeamExtractor for LLM-based sport/team extraction with caching"
```

---

### Task 3: Create SportsDataSource

**Files:**
- Create: `src/research/sports_data.py`
- Create: `tests/test_sports_data.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sports_data.py`:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.research.sports_data import SportsDataSource
from src.research.team_extractor import TeamExtractor, TeamInfo


@pytest.fixture
def extractor():
    ext = TeamExtractor(anthropic_key="test-key")
    return ext


@pytest.fixture
def source(extractor):
    return SportsDataSource(api_key="test-bdl-key", team_extractor=extractor)


def test_sports_data_name(source):
    assert source.name == "sports_data"


def test_sports_data_available_with_key(source):
    assert source.is_available() is True


def test_sports_data_unavailable_without_key():
    ext = TeamExtractor()
    s = SportsDataSource(api_key="", team_extractor=ext)
    assert s.is_available() is False


@pytest.mark.asyncio
async def test_sports_data_non_sports_market(source, extractor):
    market = MagicMock()
    market.question = "Will Bitcoin reach $80,000?"
    # TeamExtractor returns None for non-sports
    extractor._cache[market.question] = None
    result = await source.fetch(market)
    assert result["sports_is_relevant"] == 0.0
    assert result["rest_days_differential"] == 0.0
    assert result["standings_pct_delta"] == 0.0


@pytest.mark.asyncio
async def test_sports_data_returns_features(source, extractor):
    market = MagicMock()
    market.question = "Raptors vs Bulls"
    info = TeamInfo(sport="nba", team_a="Toronto Raptors", team_b="Chicago Bulls")
    extractor._cache[market.question] = info
    extractor._team_lists["nba"] = [
        {"id": 1, "full_name": "Toronto Raptors"},
        {"id": 2, "full_name": "Chicago Bulls"},
    ]

    # Mock schedule: Raptors played 2 days ago, Bulls played 1 day ago
    games_resp_a = MagicMock()
    games_resp_a.status_code = 200
    games_resp_a.json.return_value = {"data": [{"date": "2026-03-17"}]}

    games_resp_b = MagicMock()
    games_resp_b.status_code = 200
    games_resp_b.json.return_value = {"data": [{"date": "2026-03-18"}]}

    # Mock standings
    standings_resp = MagicMock()
    standings_resp.status_code = 200
    standings_resp.json.return_value = {"data": [
        {"team": {"id": 1}, "wins": 40, "losses": 20},
        {"team": {"id": 2}, "wins": 30, "losses": 30},
    ]}

    games_call_count = 0
    async def mock_get(url, **kwargs):
        nonlocal games_call_count
        if "standings" in url:
            return standings_resp
        # Track only games calls to distinguish team_a vs team_b
        games_call_count += 1
        if games_call_count <= 1:
            return games_resp_a
        return games_resp_b

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await source.fetch(market)

    assert result["sports_is_relevant"] == 1.0
    assert isinstance(result["rest_days_differential"], float)
    assert result["rest_days_differential"] != 0.0  # teams have different rest days
    assert isinstance(result["standings_pct_delta"], float)
    # Raptors: 40/(40+20) = 0.667, Bulls: 30/(30+30) = 0.5
    assert abs(result["standings_pct_delta"] - 0.167) < 0.01


@pytest.mark.asyncio
async def test_sports_data_api_error(source, extractor):
    market = MagicMock()
    market.question = "Raptors vs Bulls"
    info = TeamInfo(sport="nba", team_a="Toronto Raptors", team_b="Chicago Bulls")
    extractor._cache[market.question] = info
    extractor._team_lists["nba"] = [
        {"id": 1, "full_name": "Toronto Raptors"},
        {"id": 2, "full_name": "Chicago Bulls"},
    ]

    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        result = await source.fetch(market)
    assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sports_data.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement SportsDataSource**

Create `src/research/sports_data.py`:

```python
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
        """Compute days-since-last-game difference: team_a_rest - team_b_rest."""
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=7)).isoformat()
        end = (today - timedelta(days=1)).isoformat()

        rest_a = await self._days_since_last_game(client, sport, id_a, start, end, today)
        rest_b = await self._days_since_last_game(client, sport, id_b, start, end, today)
        return float(rest_a - rest_b)

    async def _days_since_last_game(self, client: httpx.AsyncClient,
                                     sport: str, team_id: int,
                                     start: str, end: str, today) -> int:
        """Return days since team's last game. Default 3 if unknown."""
        resp = await client.get(
            f"{BALLDONTLIE_BASE}/{sport}/games",
            headers={"Authorization": self.api_key},
            params={"team_ids[]": team_id, "start_date": start, "end_date": end},
        )
        if resp.status_code != 200:
            return 3  # default
        games = resp.json().get("data", [])
        if not games:
            return 3
        # Most recent game
        last_date_str = games[-1].get("date", "")[:10]
        try:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            return (today - last_date).days
        except ValueError:
            return 3

    async def _get_standings_delta(self, client: httpx.AsyncClient,
                                    sport: str, id_a: int, id_b: int) -> float:
        """Compute win-pct difference: team_a_pct - team_b_pct. Range -1 to 1."""
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
        """Find a team's win percentage in standings data."""
        for entry in standings:
            tid = entry.get("team", {}).get("id")
            if tid == team_id:
                wins = entry.get("wins", 0)
                losses = entry.get("losses", 0)
                total = wins + losses
                return wins / total if total > 0 else 0.0
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sports_data.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/sports_data.py tests/test_sports_data.py
git commit -m "feat: add SportsDataSource for rest-day differential and standings from BALLDONTLIE"
```

---

### Task 4: Create OddsDataSource

**Files:**
- Create: `src/research/odds_data.py`
- Create: `tests/test_odds_data.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_odds_data.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from src.research.odds_data import OddsDataSource
from src.research.team_extractor import TeamExtractor, TeamInfo


@pytest.fixture
def extractor():
    return TeamExtractor(anthropic_key="test-key")


@pytest.fixture
def source(extractor):
    return OddsDataSource(api_key="test-odds-key", team_extractor=extractor)


def test_odds_name(source):
    assert source.name == "odds_data"


def test_odds_available_with_key(source):
    assert source.is_available() is True


def test_odds_unavailable_without_key():
    s = OddsDataSource(api_key="", team_extractor=TeamExtractor())
    assert s.is_available() is False


@pytest.mark.asyncio
async def test_odds_non_sports_market(source, extractor):
    market = MagicMock()
    market.question = "Will Trump visit China?"
    extractor._cache[market.question] = None
    result = await source.fetch(market)
    assert result == {"sharp_implied_prob": 0.0}


@pytest.mark.asyncio
async def test_odds_returns_pinnacle_prob(source, extractor):
    market = MagicMock()
    market.question = "Raptors vs Bulls"
    extractor._cache[market.question] = TeamInfo(sport="nba", team_a="Toronto Raptors", team_b="Chicago Bulls")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{
        "bookmakers": [
            {"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Toronto Raptors", "price": 1.60},
                {"name": "Chicago Bulls", "price": 2.50},
            ]}]},
        ],
    }]}
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await source.fetch(market)
    # Pinnacle implied prob for team_a: 1/1.60 = 0.625
    assert abs(result["sharp_implied_prob"] - 0.625) < 0.01


@pytest.mark.asyncio
async def test_odds_api_error(source, extractor):
    market = MagicMock()
    market.question = "Raptors vs Bulls"
    extractor._cache[market.question] = TeamInfo(sport="nba", team_a="Toronto Raptors", team_b="Chicago Bulls")

    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        result = await source.fetch(market)
    assert result == {}


@pytest.mark.asyncio
async def test_odds_budget_tracking(source, extractor):
    source._monthly_count = 220  # near limit
    market = MagicMock()
    market.question = "Raptors vs Bulls"
    extractor._cache[market.question] = TeamInfo(sport="nba", team_a="Toronto Raptors", team_b="Chicago Bulls")
    result = await source.fetch(market)
    assert result == {"sharp_implied_prob": 0.0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_odds_data.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement OddsDataSource**

Create `src/research/odds_data.py`:

```python
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
        self._month_key = ""  # "2026-03" to reset counter monthly

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
        """Extract Pinnacle implied probability for team_a from odds data."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_odds_data.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/odds_data.py tests/test_odds_data.py
git commit -m "feat: add OddsDataSource for sharp-book odds from OddsPapi"
```

---

### Task 5: Add features to XGBoost model

**Files:**
- Modify: `src/predictor/features.py`
- Modify: `src/predictor/xgb_model.py`
- Modify: `src/predictor/trainer.py`
- Modify: `tests/test_predictor.py`

- [ ] **Step 1: Add 3 features to features.py**

In `src/predictor/features.py`, in the return dict of `extract_features()`, after the `"calibration_band_obs"` line, add:

```python
        # Sports data features (3)
        "rest_days_differential": sd.get("rest_days_differential", 0.0),
        "standings_pct_delta": sd.get("standings_pct_delta", 0.0),
        "sports_is_relevant": sd.get("sports_is_relevant", 0.0),
```

- [ ] **Step 2: Add to FEATURE_ORDER in xgb_model.py**

In `src/predictor/xgb_model.py`, after the lesson-derived features block, add:

```python
    # Sports data (3)
    "rest_days_differential", "standings_pct_delta", "sports_is_relevant",
```

- [ ] **Step 3: Add defaults in trainer.py Gamma fallback**

In `src/predictor/trainer.py`, in the `market_to_features()` function's features dict, after the lesson-derived defaults, add:

```python
            # Sports data defaults
            "rest_days_differential": 0.0,
            "standings_pct_delta": 0.0,
            "sports_is_relevant": 0.0,
```

- [ ] **Step 4: Update feature count in test**

In `tests/test_predictor.py`, change:

```python
    assert len(result["features"]) == 37
```

to:

```python
    assert len(result["features"]) == 40
```

- [ ] **Step 5: Run all predictor tests**

Run: `python -m pytest tests/test_predictor.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/predictor/features.py src/predictor/xgb_model.py src/predictor/trainer.py tests/test_predictor.py
git commit -m "feat: add rest_days_differential, standings_pct_delta, sports_is_relevant to XGBoost features"
```

---

### Task 6: Wire sources into pipeline + CLV diagnostic

**Files:**
- Modify: `src/pipeline.py`

- [ ] **Step 1: Add imports at top of pipeline.py**

After the existing structured source imports (around line 19-21), add:

```python
from src.research.team_extractor import TeamExtractor
from src.research.sports_data import SportsDataSource
from src.research.odds_data import OddsDataSource
```

- [ ] **Step 2: Create TeamExtractor and add new sources to StructuredDataPipeline**

In `Pipeline.__init__`, replace the `self.structured_pipeline` block (lines 79-86) with:

```python
        self.team_extractor = TeamExtractor(
            anthropic_key=self.settings.ANTHROPIC_API_KEY,
            model=self.settings.SENTIMENT_MODEL,  # reuse Haiku
        )
        self.structured_pipeline = StructuredDataPipeline(
            sources=[
                CLOBSource(),
                CoinGeckoSource(),
                FREDSource(api_key=self.settings.FRED_API_KEY),
                SportsDataSource(
                    api_key=self.settings.BALLDONTLIE_API_KEY,
                    team_extractor=self.team_extractor,
                ),
                OddsDataSource(
                    api_key=self.settings.ODDSPAPI_API_KEY,
                    team_extractor=self.team_extractor,
                ),
            ],
            timeout=self.settings.RESEARCH_TIMEOUT,
        )
```

- [ ] **Step 3: Add CLV diagnostic post-calibration**

In `Pipeline.predict()`, after the existing post-calibration feature updates (the `edge_anomaly_flag` and `calibration_band_obs` updates), add:

```python
        # Store CLV diagnostic (not an XGBoost input — for future training data)
        sharp_prob = (structured_data or {}).get("sharp_implied_prob", 0.0)
        if sharp_prob > 0:
            features["closing_line_value_delta"] = prediction.predicted_probability - sharp_prob
        else:
            features["closing_line_value_delta"] = 0.0
```

- [ ] **Step 4: Run pipeline tests**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: Same pass count as before (no new failures introduced)

- [ ] **Step 6: Commit**

```bash
git add src/pipeline.py
git commit -m "feat: wire SportsDataSource + OddsDataSource into pipeline, add CLV diagnostic"
```

---

### Task 7: Integration test

**Files:**
- No new files — manual verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All previously-passing tests still pass. New tests (test_team_extractor, test_sports_data, test_odds_data) all pass.

- [ ] **Step 2: Verify feature count consistency**

Run: `python -c "from src.predictor.xgb_model import FEATURE_ORDER; print(f'Feature count: {len(FEATURE_ORDER)}')"`
Expected: `Feature count: 40`

- [ ] **Step 3: Verify dry-run cycle doesn't crash (no API keys)**

Run: `python -c "
from src.config import Settings
from src.pipeline import Pipeline
import asyncio
s = Settings()
p = Pipeline(settings=s)
print('Pipeline initialized OK')
print(f'Sports source available: {p.structured_pipeline.sources[3].is_available()}')
print(f'Odds source available: {p.structured_pipeline.sources[4].is_available()}')
"`
Expected: Pipeline initializes, both sources report `False` (no keys set), no crash.

- [ ] **Step 4: Commit all changes**

```bash
git add -A
git commit -m "feat: external sports data features — BALLDONTLIE + OddsPapi integration"
```

---

## Post-Deployment Steps

After deploying to the droplet:

1. Sign up for free API keys:
   - BALLDONTLIE: https://www.balldontlie.io/
   - OddsPapi: https://oddspapi.io/

2. Add to `.env`:
   ```env
   BALLDONTLIE_API_KEY=your-key-here
   ODDSPAPI_API_KEY=your-key-here
   ```

3. Retrain the model (required — feature count changed):
   ```bash
   source /opt/polymarket-bot/venv/bin/activate
   python3 run.py --train
   ```

4. Restart the trading service:
   ```bash
   sudo systemctl restart polymarket-trader
   ```
