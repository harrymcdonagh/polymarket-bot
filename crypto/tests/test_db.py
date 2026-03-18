import pytest
from src.db import Database


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    d.init()
    return d


def test_crypto_tables_created(db):
    conn = db._conn()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "crypto_candles" in tables
    assert "crypto_backtests" in tables
    assert "crypto_trades" in tables
    assert "crypto_incubation" in tables
    assert "crypto_pnl_daily" in tables


def test_save_and_get_crypto_trade(db):
    db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt123",
        side="YES", entry_price=0.52, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=1.50,
        status="dry_run_open", signal_data='{"macd_hist": 0.5}',
        token_id="tok123",
    )
    trades = db.get_open_crypto_trades()
    assert len(trades) == 1
    assert trades[0]["strategy"] == "macd_hist"
    assert trades[0]["token_id"] == "tok123"


def test_settle_crypto_trade(db):
    db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt1",
        side="YES", entry_price=0.50, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=1.50,
        status="dry_run_open", signal_data="{}",
    )
    trades = db.get_open_crypto_trades()
    updated = db.settle_crypto_trade(trades[0]["id"], status="dry_run_won", pnl=1.47)
    assert updated is True
    settled = db.get_settled_crypto_trades(limit=10)
    assert len(settled) == 1
    assert settled[0]["pnl"] == 1.47


def test_settle_with_expected_status_guard(db):
    db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt1",
        side="YES", entry_price=0.50, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=1.50,
        status="dry_run_open", signal_data="{}",
    )
    trades = db.get_open_crypto_trades()
    tid = trades[0]["id"]
    assert db.settle_crypto_trade(tid, "dry_run_won", 1.47, expected_status="dry_run_open") is True
    assert db.settle_crypto_trade(tid, "dry_run_lost", -1.53, expected_status="dry_run_open") is False


def test_get_crypto_daily_pnl(db):
    pnl = db.get_crypto_daily_pnl()
    assert pnl == 0.0


def test_save_and_get_candles(db):
    candles = [
        {"symbol": "BTC", "timestamp": "2026-03-18T12:00:00",
         "open": 84000, "high": 84100, "low": 83900, "close": 84050, "volume": 100},
        {"symbol": "BTC", "timestamp": "2026-03-18T12:01:00",
         "open": 84050, "high": 84150, "low": 83950, "close": 84100, "volume": 120},
    ]
    db.save_crypto_candles(candles)
    result = db.get_crypto_candles("BTC", limit=10)
    assert len(result) == 2


def test_save_and_get_backtest(db):
    db.save_crypto_backtest(
        strategy="macd_hist",
        params='{"macd_fast":3,"macd_slow":15,"macd_signal":3}',
        symbol="BTC", total_trades=100, win_rate=0.55,
        expectancy=0.03, total_pnl=45.0, max_drawdown=-12.0,
        profit_factor=1.2, sharpe=1.5,
    )
    results = db.get_top_crypto_backtests(limit=5)
    assert len(results) == 1
    assert results[0]["strategy"] == "macd_hist"


def test_upsert_crypto_pnl_daily(db):
    db.upsert_crypto_pnl_daily(
        date="2026-03-18", trades_count=5, wins=3, losses=2,
        gross_pnl=3.0, fees=0.15, net_pnl=2.85, bankroll=97.85,
    )
    rows = db.get_crypto_pnl_history()
    assert len(rows) == 1
    assert rows[0]["net_pnl"] == 2.85


def test_get_or_create_incubation(db):
    inc = db.get_or_create_incubation("macd_hist")
    assert inc["strategy"] == "macd_hist"
    assert inc["position_size"] == 1.50
    inc2 = db.get_or_create_incubation("macd_hist")
    assert inc2["id"] == inc["id"]


def test_get_crypto_trade_stats(db):
    stats = db.get_crypto_trade_stats()
    assert stats["total_trades"] == 0
    assert stats["win_rate"] == 0.0


def test_get_crypto_strategy_stats(db):
    stats = db.get_crypto_strategy_stats()
    assert stats == []
