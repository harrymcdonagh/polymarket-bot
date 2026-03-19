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
