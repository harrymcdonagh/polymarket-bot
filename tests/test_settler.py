import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.settler.settler import Settler
from src.db import Database


@pytest.fixture
def tmp_db(tmp_path):
    db = Database(path=str(tmp_path / "test.db"))
    db.init()
    return db


@pytest.fixture
def settler(tmp_db):
    notifier = MagicMock()
    notifier.is_enabled = False
    return Settler(db=tmp_db, notifier=notifier, gamma_url="https://gamma-api.polymarket.com")


def test_calc_hypothetical_pnl_win_yes(settler):
    # Bought YES at $0.40 for $10. Market resolved YES.
    # Shares = 10 / 0.40 = 25. Payout = 25 * 1.0 = 25. PnL = 25 - 10 = 15
    pnl = settler.calc_hypothetical_pnl(side="YES", amount=10.0, price=0.40, outcome="YES")
    assert pnl == pytest.approx(15.0)


def test_calc_hypothetical_pnl_loss_yes(settler):
    # Bought YES at $0.40 for $10. Market resolved NO.
    pnl = settler.calc_hypothetical_pnl(side="YES", amount=10.0, price=0.40, outcome="NO")
    assert pnl == pytest.approx(-10.0)


def test_calc_hypothetical_pnl_win_no(settler):
    # Bought NO. yes_price=0.60, so NO price = 0.40. Amount=$10.
    # Shares = 10 / 0.40 = 25. Payout = 25. PnL = 25 - 10 = 15
    pnl = settler.calc_hypothetical_pnl(side="NO", amount=10.0, price=0.60, outcome="NO")
    assert pnl == pytest.approx(15.0)


def test_calc_hypothetical_pnl_loss_no(settler):
    # Bought NO at $0.60 for $10. Market resolved YES.
    pnl = settler.calc_hypothetical_pnl(side="NO", amount=10.0, price=0.60, outcome="YES")
    assert pnl == pytest.approx(-10.0)


@pytest.mark.asyncio
async def test_check_resolution_returns_none_for_active(settler):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"closed": False, "resolved": False}

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        result = await settler.check_resolution("condition-123")
        assert result is None


@pytest.mark.asyncio
async def test_check_resolution_returns_outcome(settler):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True,
        "resolved": True,
        "outcomePrices": "[\"1\",\"0\"]",
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        result = await settler.check_resolution("condition-123")
        assert result == "YES"


@pytest.mark.asyncio
async def test_run_settles_resolved_trades(settler, tmp_db):
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True, "resolved": True, "outcomePrices": "[\"1\",\"0\"]"
    }

    settler.postmortem = AsyncMock()
    settler.postmortem.analyze_loss = AsyncMock(return_value={})

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        await settler.run()

    trades = tmp_db.get_unresolved_dry_run_trades()
    assert len(trades) == 0
