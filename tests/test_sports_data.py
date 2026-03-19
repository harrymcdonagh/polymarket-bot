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

    games_resp_a = MagicMock()
    games_resp_a.status_code = 200
    games_resp_a.json.return_value = {"data": [{"date": "2026-03-17"}]}

    games_resp_b = MagicMock()
    games_resp_b.status_code = 200
    games_resp_b.json.return_value = {"data": [{"date": "2026-03-18"}]}

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
        games_call_count += 1
        if games_call_count <= 1:
            return games_resp_a
        return games_resp_b

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await source.fetch(market)

    assert result["sports_is_relevant"] == 1.0
    assert isinstance(result["rest_days_differential"], float)
    assert result["rest_days_differential"] != 0.0
    assert isinstance(result["standings_pct_delta"], float)
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
