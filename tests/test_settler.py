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
    # Shares = 10 / 0.40 = 25. Payout = 25 * 1.0 = 25. PnL = 25 - 10 - fee(0.20) = 14.80
    pnl = settler.calc_hypothetical_pnl(side="YES", amount=10.0, price=0.40, outcome="YES")
    assert pnl == pytest.approx(14.80)


def test_calc_hypothetical_pnl_loss_yes(settler):
    # Bought YES at $0.40 for $10. Market resolved NO.
    # PnL = -10 - fee(0.20) = -10.20
    pnl = settler.calc_hypothetical_pnl(side="YES", amount=10.0, price=0.40, outcome="NO")
    assert pnl == pytest.approx(-10.20)


def test_calc_hypothetical_pnl_win_no(settler):
    # Bought NO. yes_price=0.60, so NO price = 0.40. Amount=$10.
    # Shares = 10 / 0.40 = 25. Payout = 25. PnL = 25 - 10 - fee(0.20) = 14.80
    pnl = settler.calc_hypothetical_pnl(side="NO", amount=10.0, price=0.60, outcome="NO")
    assert pnl == pytest.approx(14.80)


def test_calc_hypothetical_pnl_loss_no(settler):
    # Bought NO at $0.60 for $10. Market resolved YES.
    # PnL = -10 - fee(0.20) = -10.20
    pnl = settler.calc_hypothetical_pnl(side="NO", amount=10.0, price=0.60, outcome="YES")
    assert pnl == pytest.approx(-10.20)


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

    with patch.object(settler, "refresh_open_positions", new_callable=AsyncMock):
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            await settler.run()

    trades = tmp_db.get_unresolved_dry_run_trades()
    assert len(trades) == 0


@pytest.mark.asyncio
async def test_run_saves_trade_metrics(settler, tmp_db):
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    tmp_db.save_prediction(
        market_id="cond-1", question="Test?", market_yes_price=0.5,
        predicted_prob=0.7, xgb_prob=0.6, llm_prob=0.75,
        edge=0.10, confidence=0.8, recommended_side="YES",
        approved=True, bet_size=5.0,
    )

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True, "resolved": True, "outcomePrices": "[\"1\",\"0\"]"
    }

    with patch.object(settler, "refresh_open_positions", new_callable=AsyncMock):
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            await settler.run()

    conn = tmp_db._conn()
    metric = conn.execute("SELECT * FROM trade_metrics WHERE trade_id = 1").fetchone()
    assert metric is not None
    assert metric["was_correct"] == 1
    assert metric["actual_outcome"] == "YES"
    assert metric["edge_at_entry"] == 0.10


@pytest.mark.asyncio
async def test_postmortem_skipped_for_low_edge_wrong(settler, tmp_db):
    """Postmortem should NOT run when edge < 5% even if wrong."""
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    tmp_db.save_prediction(
        market_id="cond-1", question="Test?", market_yes_price=0.5,
        predicted_prob=0.52, xgb_prob=0.5, llm_prob=0.53,
        edge=0.02, confidence=0.3, recommended_side="YES",
        approved=True, bet_size=5.0,
    )

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True, "resolved": True, "outcomePrices": "[\"0\",\"1\"]"
    }

    mock_postmortem = AsyncMock()
    mock_postmortem.analyze_loss = AsyncMock(return_value={})
    settler.postmortem = mock_postmortem

    with patch.object(settler, "refresh_open_positions", new_callable=AsyncMock):
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            await settler.run()

    mock_postmortem.analyze_loss.assert_not_called()


@pytest.mark.asyncio
async def test_postmortem_runs_for_high_edge_wrong(settler, tmp_db):
    """Postmortem SHOULD run when edge > 5% and wrong."""
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    tmp_db.save_prediction(
        market_id="cond-1", question="Test?", market_yes_price=0.5,
        predicted_prob=0.7, xgb_prob=0.6, llm_prob=0.75,
        edge=0.15, confidence=0.8, recommended_side="YES",
        approved=True, bet_size=5.0,
    )

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True, "resolved": True, "outcomePrices": "[\"0\",\"1\"]"
    }

    mock_postmortem = AsyncMock()
    mock_postmortem.analyze_loss = AsyncMock(return_value={})
    settler.postmortem = mock_postmortem

    with patch.object(settler, "refresh_open_positions", new_callable=AsyncMock):
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            await settler.run()

    mock_postmortem.analyze_loss.assert_called_once()


def _insert_snapshot(db, condition_id, yes_price):
    """Helper to insert a market snapshot with a given price."""
    from src.models import ScannedMarket
    from datetime import datetime, timezone
    market = ScannedMarket(
        condition_id=condition_id, question="Test?", slug="test",
        token_yes_id="ty", token_no_id="tn",
        yes_price=yes_price, no_price=1 - yes_price, spread=0.01,
        liquidity=10000, volume_24h=5000,
        end_date=None, days_to_resolution=10,
        flags=[], scanned_at=datetime.now(timezone.utc),
    )
    db.save_market_snapshots_batch([market])


@pytest.mark.asyncio
async def test_refresh_open_positions_updates_prices(settler, tmp_db):
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    _insert_snapshot(tmp_db, "cond-1", 0.65)

    await settler.refresh_open_positions()

    conn = tmp_db._conn()
    row = conn.execute("SELECT current_price, price_updated_at FROM trades WHERE id = 1").fetchone()
    assert row["current_price"] == pytest.approx(0.65)
    assert row["price_updated_at"] is not None


@pytest.mark.asyncio
async def test_refresh_open_positions_no_snapshot(settler, tmp_db):
    """No snapshot means no price update."""
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)

    await settler.refresh_open_positions()

    conn = tmp_db._conn()
    row = conn.execute("SELECT current_price FROM trades WHERE id = 1").fetchone()
    assert row["current_price"] is None


@pytest.mark.asyncio
async def test_refresh_updates_both_trades_same_market(settler, tmp_db):
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    tmp_db.save_trade("cond-1", "NO", 5.0, 0.5, status="dry_run", predicted_prob=0.3)
    _insert_snapshot(tmp_db, "cond-1", 0.60)

    await settler.refresh_open_positions()

    conn = tmp_db._conn()
    rows = conn.execute("SELECT current_price FROM trades WHERE market_id = 'cond-1'").fetchall()
    assert all(r["current_price"] == pytest.approx(0.60) for r in rows)


@pytest.mark.asyncio
async def test_run_calls_refresh_before_settlement(settler, tmp_db):
    """Verify run() calls refresh_open_positions before checking resolutions."""
    call_order = []

    async def mock_refresh():
        call_order.append("refresh")

    with patch.object(settler, "refresh_open_positions", side_effect=mock_refresh):
        tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"resolved": False}
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            await settler.run()

    assert call_order[0] == "refresh"
