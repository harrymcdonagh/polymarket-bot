import pytest
from src.db import Database
from src.tracker import IncubationTracker


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    d.init()
    return d


@pytest.fixture
def tracker(db):
    return IncubationTracker(db=db, scale_sequence=[1.50, 5, 10, 25, 50, 100],
                             min_days=14, max_consecutive_loss_days=3)


def test_update_after_win(tracker, db):
    tracker.update_after_trade("macd_hist", won=True, pnl=1.47)
    inc = db.get_or_create_incubation("macd_hist")
    assert inc["total_trades"] == 1
    assert inc["wins"] == 1
    assert inc["losses"] == 0
    assert inc["total_pnl"] == 1.47


def test_update_after_loss(tracker, db):
    tracker.update_after_trade("macd_hist", won=False, pnl=-1.53)
    inc = db.get_or_create_incubation("macd_hist")
    assert inc["total_trades"] == 1
    assert inc["wins"] == 0
    assert inc["losses"] == 1


def test_get_current_size_default(tracker):
    size = tracker.get_current_size("macd_hist")
    assert size == 1.50


def test_check_retire_not_enough_days(tracker, db):
    # Not enough PnL history — should not retire
    assert tracker.check_retire("macd_hist") is False


def test_check_retire_consecutive_losses(tracker, db):
    # Insert 3 consecutive losing days
    for i, date in enumerate(["2026-03-15", "2026-03-16", "2026-03-17"]):
        db.upsert_crypto_pnl_daily(date=date, trades_count=5, wins=1, losses=4,
                                    gross_pnl=-2.0, fees=0.1, net_pnl=-2.1, bankroll=90.0)
    assert tracker.check_retire("macd_hist") is True
    inc = db.get_or_create_incubation("macd_hist")
    assert inc["status"] == "retired"
