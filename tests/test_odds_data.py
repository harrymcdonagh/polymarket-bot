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
