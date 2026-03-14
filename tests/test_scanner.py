import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from src.config import Settings
from src.db import Database
from src.scanner.scanner import MarketScanner
from src.models import ScanFlag


def test_settings_defaults():
    settings = Settings(ANTHROPIC_API_KEY="test-key")
    assert settings.MAX_BET_FRACTION == 0.05
    assert settings.CONFIDENCE_THRESHOLD == 0.7
    assert settings.BANKROLL == 1000.0
    assert settings.POLYMARKET_CLOB_URL == "https://clob.polymarket.com"
    assert settings.POLYMARKET_GAMMA_URL == "https://gamma-api.polymarket.com"


def test_db_init_creates_tables(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t[0] for t in tables}
    assert "scanned_markets" in table_names
    assert "trades" in table_names
    assert "postmortems" in table_names
    assert "lessons" in table_names
    conn.close()


def test_db_save_and_load_trade(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    db.save_trade(
        market_id="0xabc",
        side="YES",
        amount=50.0,
        price=0.45,
        order_id="order123",
    )
    trades = db.get_open_trades()
    assert len(trades) == 1
    assert trades[0]["market_id"] == "0xabc"
    assert trades[0]["status"] == "pending"


def _make_market(liquidity=10000, volume=5000, spread=0.03, days_out=30):
    end = datetime.now(timezone.utc) + timedelta(days=days_out)
    return {
        "conditionId": "0xabc123",
        "question": "Will X happen?",
        "slug": "will-x-happen",
        "outcomePrices": '["0.55", "0.45"]',
        "clobTokenIds": '["tok_yes", "tok_no"]',
        "liquidityNum": liquidity,
        "volume24hr": volume,
        "endDateIso": end.isoformat(),
        "active": True,
        "closed": False,
    }


def test_scanner_filters_low_liquidity():
    settings = Settings(ANTHROPIC_API_KEY="test", MIN_LIQUIDITY=10000)
    scanner = MarketScanner(settings)
    market = _make_market(liquidity=500)
    result = scanner._passes_filters(market)
    assert result is False


def test_scanner_flags_wide_spread():
    settings = Settings(ANTHROPIC_API_KEY="test", SPREAD_ALERT_THRESHOLD=0.10)
    scanner = MarketScanner(settings)
    market = _make_market(spread=0.15)
    flags = scanner._detect_flags(market, spread=0.15)
    assert "wide_spread" in [f.value for f in flags]


def test_scanner_passes_good_market():
    settings = Settings(ANTHROPIC_API_KEY="test")
    scanner = MarketScanner(settings)
    market = _make_market(liquidity=20000, volume=5000)
    result = scanner._passes_filters(market)
    assert result is True


def test_scanner_flags_mispriced():
    settings = Settings(ANTHROPIC_API_KEY="test")
    scanner = MarketScanner(settings)
    # Prices that don't sum to 1.0
    market = _make_market()
    market["outcomePrices"] = '["0.60", "0.30"]'
    flags = scanner._detect_flags(market, spread=0.10)
    assert ScanFlag.MISPRICED in flags


def test_scanner_no_mispriced_flag_for_normal_market():
    settings = Settings(ANTHROPIC_API_KEY="test")
    scanner = MarketScanner(settings)
    market = _make_market()
    flags = scanner._detect_flags(market, spread=0.02)
    assert ScanFlag.MISPRICED not in flags


def test_scanner_flags_high_volume():
    settings = Settings(ANTHROPIC_API_KEY="test")
    scanner = MarketScanner(settings)
    market = _make_market(volume=100000)
    flags = scanner._detect_flags(market, spread=0.02)
    assert ScanFlag.HIGH_VOLUME in flags


def test_scanner_filters_near_resolved():
    settings = Settings(ANTHROPIC_API_KEY="test")
    scanner = MarketScanner(settings)
    market = _make_market()
    market["outcomePrices"] = '["0.98", "0.02"]'
    result = scanner._passes_filters(market)
    assert result is False


def test_scanner_filters_expired_market():
    settings = Settings(ANTHROPIC_API_KEY="test")
    scanner = MarketScanner(settings)
    market = _make_market(days_out=-5)
    result = scanner._passes_filters(market)
    assert result is False


def test_db_market_snapshots_table_exists(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t[0] for t in tables}
    assert "market_snapshots" in table_names
    conn.close()


def test_db_trade_stats(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    db.save_trade("0x1", "YES", 50.0, 0.5, "o1")
    db.update_trade_status(1, "settled", 50.0)
    db.save_trade("0x2", "NO", 30.0, 0.6, "o2")
    db.update_trade_status(2, "settled", -30.0)
    stats = db.get_trade_stats()
    assert stats["total_trades"] == 2
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["total_pnl"] == 20.0


def test_db_snapshot_count(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    assert db.get_snapshot_count() == 0


def test_config_rejects_zero_bankroll():
    with pytest.raises(Exception):
        Settings(ANTHROPIC_API_KEY="test", BANKROLL=0)


def test_config_rejects_invalid_bet_fraction():
    with pytest.raises(Exception):
        Settings(ANTHROPIC_API_KEY="test", MAX_BET_FRACTION=1.5)


def test_config_rejects_invalid_confidence():
    with pytest.raises(Exception):
        Settings(ANTHROPIC_API_KEY="test", CONFIDENCE_THRESHOLD=-0.1)


def test_config_rejects_invalid_log_level():
    with pytest.raises(Exception):
        Settings(ANTHROPIC_API_KEY="test", LOG_LEVEL="BOGUS")


def test_config_defaults_log_level():
    settings = Settings(ANTHROPIC_API_KEY="test")
    assert settings.LOG_LEVEL == "INFO"
    assert settings.LOOP_INTERVAL == 300
