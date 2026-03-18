import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.settler import CryptoSettler, calc_crypto_pnl
from src.db import Database
from src.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(DB_PATH=str(tmp_path / "test.db"))


@pytest.fixture
def settler(settings):
    s = CryptoSettler(settings)
    return s


def test_calc_pnl_win():
    pnl = calc_crypto_pnl(0.50, 1.50, won=True, fee_pct=0.02)
    assert abs(pnl - 1.47) < 0.01


def test_calc_pnl_loss():
    pnl = calc_crypto_pnl(0.50, 1.50, won=False, fee_pct=0.02)
    assert abs(pnl - (-1.53)) < 0.01


async def test_settle_no_trades(settler):
    await settler.run()
    # No error, just returns


async def test_settle_resolves_trade(settler):
    # Insert an open trade
    settler.db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt1",
        side="YES", entry_price=0.50, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=1.50,
        status="dry_run_open", signal_data="{}", token_id="tok1",
    )
    # Mock scanner to return YES resolution
    settler.scanner.check_resolution = AsyncMock(return_value="YES")

    await settler.run()

    settled = settler.db.get_settled_crypto_trades()
    assert len(settled) == 1
    assert settled[0]["status"] == "dry_run_won"
    assert settled[0]["pnl"] > 0


async def test_settle_race_condition_guard(settler):
    settler.db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt1",
        side="YES", entry_price=0.50, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=1.50,
        status="dry_run_open", signal_data="{}", token_id="tok1",
    )
    settler.scanner.check_resolution = AsyncMock(return_value="YES")

    # First settle
    await settler.run()
    # Second settle — should skip (already settled)
    settler.scanner.check_resolution = AsyncMock(return_value="YES")
    await settler.run()

    settled = settler.db.get_settled_crypto_trades()
    assert len(settled) == 1  # Only one settlement
