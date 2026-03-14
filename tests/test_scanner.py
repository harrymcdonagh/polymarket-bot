import sqlite3
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
