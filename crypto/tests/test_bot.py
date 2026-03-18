import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
import numpy as np
from src.bot import CryptoBot, is_5min_boundary, calc_crypto_pnl


def _make_candle_df(n=100):
    np.random.seed(42)
    base = 84000.0
    prices = base + np.cumsum(np.random.randn(n) * 10)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-03-18T12:00:00", periods=n, freq="1min", tz="UTC"),
        "open": prices, "high": prices + 5, "low": prices - 5,
        "close": prices + np.random.randn(n) * 3,
        "volume": np.random.randint(50, 500, n).astype(float),
    })


def test_is_5min_boundary():
    from datetime import datetime, timezone
    assert is_5min_boundary(datetime(2026, 3, 18, 12, 0, 0, tzinfo=timezone.utc)) is True
    assert is_5min_boundary(datetime(2026, 3, 18, 12, 5, 0, tzinfo=timezone.utc)) is True
    assert is_5min_boundary(datetime(2026, 3, 18, 12, 3, 0, tzinfo=timezone.utc)) is False


def test_calc_crypto_pnl():
    pnl = calc_crypto_pnl(entry_price=0.50, stake=1.50, won=True, fee_pct=0.02)
    assert abs(pnl - 1.47) < 0.01
    pnl = calc_crypto_pnl(entry_price=0.50, stake=1.50, won=False, fee_pct=0.02)
    assert abs(pnl - (-1.53)) < 0.01


def test_bot_initializes(tmp_path):
    from src.config import Settings
    settings = Settings(DB_PATH=str(tmp_path / "test.db"), CRYPTO_STRATEGY="macd_hist",
                        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}')
    bot = CryptoBot(settings=settings, dry_run=True)
    assert bot.strategy is not None
    assert bot.strategy_name == "macd_hist"


async def test_bot_cycle_no_signal(tmp_path):
    from src.config import Settings
    settings = Settings(DB_PATH=str(tmp_path / "test.db"), CRYPTO_STRATEGY="macd_hist",
                        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}')
    bot = CryptoBot(settings=settings, dry_run=True)
    bot.feed = MagicMock()
    bot.feed.fetch_candles = AsyncMock(return_value=_make_candle_df(20))
    bot.scanner = MagicMock()
    bot.scanner.check_resolution = AsyncMock(return_value=None)
    with patch("src.bot.is_5min_boundary", return_value=True):
        await bot._run_cycle()
    # The real db.save_crypto_trade was not mocked, so just verify no trade was saved
    # by checking the open trades table is still empty
    assert bot.db.get_open_crypto_trades() == []


def test_bot_unknown_strategy_raises(tmp_path):
    from src.config import Settings
    settings = Settings(DB_PATH=str(tmp_path / "test.db"), CRYPTO_STRATEGY="nonexistent",
                        CRYPTO_STRATEGY_PARAMS='{}')
    with pytest.raises(ValueError, match="Unknown strategy"):
        CryptoBot(settings=settings, dry_run=True)


def test_calc_crypto_pnl_zero_fee():
    # Won: (1/0.8 - 1) * 10 = 2.5
    pnl = calc_crypto_pnl(entry_price=0.80, stake=10.0, won=True, fee_pct=0.0)
    assert abs(pnl - 2.5) < 0.001
    # Lost: -10.0
    pnl = calc_crypto_pnl(entry_price=0.80, stake=10.0, won=False, fee_pct=0.0)
    assert abs(pnl - (-10.0)) < 0.001


async def test_settle_open_trades_resolves(tmp_path):
    """Settled trade: DB settle and tracker update are called."""
    from src.config import Settings
    settings = Settings(DB_PATH=str(tmp_path / "test.db"), CRYPTO_STRATEGY="macd_hist",
                        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}')
    bot = CryptoBot(settings=settings, dry_run=True)

    open_trade = {
        "id": 1,
        "strategy": "macd_hist",
        "side": "YES",
        "entry_price": 0.6,
        "amount": 1.5,
        "status": "dry_run_open",
        "market_id": "mkt_abc",
        "token_id": "tok_abc",
    }
    bot.db.get_open_crypto_trades = MagicMock(return_value=[open_trade])
    bot.db.settle_crypto_trade = MagicMock(return_value=True)
    bot.tracker.update_after_trade = MagicMock()
    bot.scanner.check_resolution = AsyncMock(return_value="YES")

    await bot._settle_open_trades()

    bot.db.settle_crypto_trade.assert_called_once()
    call_kwargs = bot.db.settle_crypto_trade.call_args
    assert call_kwargs[1]["status"] == "dry_run_won"
    # entry=0.6, stake=1.5, won=True, fee=0.02: (1/0.6 - 1)*1.5 - 0.03 = 0.97
    bot.tracker.update_after_trade.assert_called_once_with("macd_hist", won=True, pnl=pytest.approx(0.97, abs=0.01))


async def test_settle_open_trades_no_resolution(tmp_path):
    """No resolution returned: nothing is settled."""
    from src.config import Settings
    settings = Settings(DB_PATH=str(tmp_path / "test.db"), CRYPTO_STRATEGY="macd_hist",
                        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}')
    bot = CryptoBot(settings=settings, dry_run=True)

    open_trade = {
        "id": 2,
        "strategy": "macd_hist",
        "side": "YES",
        "entry_price": 0.6,
        "amount": 1.5,
        "status": "dry_run_open",
        "market_id": "mkt_abc",
        "token_id": "tok_abc",
    }
    bot.db.get_open_crypto_trades = MagicMock(return_value=[open_trade])
    bot.db.settle_crypto_trade = MagicMock()
    bot.scanner.check_resolution = AsyncMock(return_value=None)

    await bot._settle_open_trades()

    bot.db.settle_crypto_trade.assert_not_called()


async def test_run_cycle_risk_blocked(tmp_path):
    """When risk check fails, no trade is saved."""
    from src.config import Settings
    settings = Settings(DB_PATH=str(tmp_path / "test.db"), CRYPTO_STRATEGY="macd_hist",
                        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}')
    bot = CryptoBot(settings=settings, dry_run=True)
    bot.feed = MagicMock()
    bot.feed.fetch_candles = AsyncMock(return_value=_make_candle_df(100))
    bot.scanner = MagicMock()
    bot.scanner.check_resolution = AsyncMock(return_value=None)
    bot.scanner.find_active_5min_market = AsyncMock(return_value={
        "market_id": "mkt1", "token_id": "tok1",
        "yes_price": 0.6, "no_price": 0.4, "strike_price": 84000.0,
    })
    # Force signal=1
    bot.strategy.generate_signal = MagicMock(return_value=(1, {"reason": "test"}))
    # Block risk
    bot.risk_manager.check = MagicMock(return_value=(False, "daily loss limit"))
    bot.db.save_crypto_trade = MagicMock()
    bot.db.get_crypto_daily_pnl = MagicMock(return_value=-25.0)
    bot.db.get_open_crypto_trades = MagicMock(return_value=[])

    with patch("src.bot.is_5min_boundary", return_value=True):
        await bot._run_cycle()

    bot.db.save_crypto_trade.assert_not_called()


async def test_run_cycle_saves_trade_dry_run(tmp_path):
    """With valid signal, risk OK, market found: trade is saved."""
    from src.config import Settings
    settings = Settings(DB_PATH=str(tmp_path / "test.db"), CRYPTO_STRATEGY="macd_hist",
                        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}')
    bot = CryptoBot(settings=settings, dry_run=True)
    bot.feed = MagicMock()
    bot.feed.fetch_candles = AsyncMock(return_value=_make_candle_df(100))
    bot.scanner = MagicMock()
    bot.scanner.check_resolution = AsyncMock(return_value=None)
    bot.scanner.find_active_5min_market = AsyncMock(return_value={
        "market_id": "mkt1", "token_id": "tok1",
        "yes_price": 0.6, "no_price": 0.4, "strike_price": 84000.0,
    })
    bot.strategy.generate_signal = MagicMock(return_value=(1, {"reason": "test"}))
    bot.risk_manager.check = MagicMock(return_value=(True, ""))
    bot.db.save_crypto_trade = MagicMock(return_value=1)
    bot.db.get_crypto_daily_pnl = MagicMock(return_value=0.0)
    bot.db.get_open_crypto_trades = MagicMock(return_value=[])
    bot.tracker.get_current_size = MagicMock(return_value=1.5)

    with patch("src.bot.is_5min_boundary", return_value=True):
        await bot._run_cycle()

    bot.db.save_crypto_trade.assert_called_once()
    call_kwargs = bot.db.save_crypto_trade.call_args[1]
    assert call_kwargs["side"] == "YES"
    assert call_kwargs["status"] == "dry_run_open"
    assert call_kwargs["strategy"] == "macd_hist"


async def test_run_stops_after_max_errors(tmp_path):
    """run() stops the loop after _max_errors consecutive errors."""
    from src.config import Settings
    settings = Settings(DB_PATH=str(tmp_path / "test.db"), CRYPTO_STRATEGY="macd_hist",
                        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}')
    bot = CryptoBot(settings=settings, dry_run=True)
    bot._max_errors = 2
    bot.feed.close = AsyncMock()

    call_count = 0

    async def failing_cycle():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    bot._run_cycle = failing_cycle

    with patch("asyncio.sleep", new=AsyncMock()):
        await bot.run()

    assert call_count == 2
    bot.feed.close.assert_called_once()
