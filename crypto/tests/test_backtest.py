import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock
from src.backtester.engine import BacktestEngine
from src.backtester.runner import BacktestRunner, PARAM_GRID
from src.strategies.macd_hist import MACDHistStrategy


def _make_candle_df(n=500):
    np.random.seed(42)
    base = 84000.0
    prices = base + np.cumsum(np.random.randn(n) * 10)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-03-18", periods=n, freq="1min", tz="UTC"),
        "open": prices,
        "high": prices + np.abs(np.random.randn(n) * 5),
        "low": prices - np.abs(np.random.randn(n) * 5),
        "close": prices + np.random.randn(n) * 3,
        "volume": np.random.randint(50, 500, n).astype(float),
    })


def test_backtest_engine_runs():
    strat = MACDHistStrategy(macd_fast=3, macd_slow=15, macd_signal=3)
    engine = BacktestEngine(entry_price=0.50, fee_pct=0.02, stake=1.50)
    result = engine.run(strat, _make_candle_df(500), indicator_params={"macd_fast": 3, "macd_slow": 15, "macd_signal": 3})
    assert "total_trades" in result
    assert "win_rate" in result
    assert "expectancy" in result
    assert "total_pnl" in result
    assert "max_drawdown" in result
    assert "profit_factor" in result
    assert "sharpe" in result


def test_backtest_engine_no_trades():
    strat = MACDHistStrategy()
    engine = BacktestEngine()
    result = engine.run(strat, _make_candle_df(20))
    assert result["total_trades"] == 0
    assert result["win_rate"] == 0.0


def test_backtest_engine_pnl_math():
    engine = BacktestEngine(entry_price=0.50, fee_pct=0.02, stake=1.50)
    assert abs(engine._calc_trade_pnl(won=True) - 1.47) < 0.01
    assert abs(engine._calc_trade_pnl(won=False) - (-1.53)) < 0.01


def test_param_grid_has_all_strategies():
    assert set(PARAM_GRID.keys()) == {"macd_hist", "rsi_bb", "vwap_cap", "ema_cross"}


def test_runner_runs_grid():
    db = MagicMock()
    runner = BacktestRunner(db=db)
    results = runner.run_grid(_make_candle_df(500), strategies=["macd_hist"], symbol="BTC")
    assert len(results) > 0
    assert results[0]["strategy"] == "macd_hist"
    assert db.save_crypto_backtest.call_count == len(PARAM_GRID["macd_hist"])
