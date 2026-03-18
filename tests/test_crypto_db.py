import pytest
from src.db import Database


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    d.init()
    return d


def test_crypto_stats_no_tables(db):
    """Returns empty stats when crypto tables don't exist."""
    stats = db.get_crypto_trade_stats()
    assert stats["total_trades"] == 0
    assert stats["win_rate"] == 0.0


def test_crypto_trades_no_tables(db):
    assert db.get_recent_crypto_trades() == []


def test_crypto_pnl_no_tables(db):
    assert db.get_crypto_pnl_history() == []


def test_crypto_strategies_no_tables(db):
    assert db.get_crypto_strategy_stats() == []


def test_incubations_no_tables(db):
    assert db.get_all_incubations() == []


def test_backtests_no_tables(db):
    assert db.get_top_crypto_backtests() == []


def test_table_exists_helper(db):
    assert db._table_exists("trades") is True
    assert db._table_exists("nonexistent_table") is False
