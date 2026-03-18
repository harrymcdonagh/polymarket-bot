import pytest
import pandas as pd
import numpy as np
from src.strategies.base import CryptoStrategy
from src.strategies.macd_hist import MACDHistStrategy
from src.strategies.rsi_bb import RSIBBStrategy
from src.strategies.vwap_cap import VWAPCapStrategy
from src.strategies.ema_cross import EMACrossStrategy
from src.indicators import compute_indicators


def _make_candle_df(n=100):
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


def test_base_class_is_abstract():
    with pytest.raises(TypeError):
        CryptoStrategy()


class TestMACDHist:
    def test_generate_signal_returns_tuple(self):
        strat = MACDHistStrategy(macd_fast=3, macd_slow=15, macd_signal=3)
        df = compute_indicators(_make_candle_df(100), macd_fast=3, macd_slow=15, macd_signal=3)
        signal, meta = strat.generate_signal(df)
        assert signal in (-1, 0, 1)
        assert isinstance(meta, dict)

    def test_generate_signal_returns_zero_with_nan(self):
        strat = MACDHistStrategy()
        df = compute_indicators(_make_candle_df(10))
        signal, meta = strat.generate_signal(df)
        assert signal == 0

    def test_backtest_signal_returns_trade_list(self):
        strat = MACDHistStrategy(macd_fast=3, macd_slow=15, macd_signal=3)
        df = compute_indicators(_make_candle_df(200), macd_fast=3, macd_slow=15, macd_signal=3)
        trades = strat.backtest_signal(df)
        assert isinstance(trades, list)
        for t in trades:
            assert "signal" in t and "entry_idx" in t and "exit_idx" in t

    def test_params_dict(self):
        strat = MACDHistStrategy(macd_fast=3, macd_slow=15, macd_signal=3)
        assert strat.params_dict() == {"macd_fast": 3, "macd_slow": 15, "macd_signal": 3}


class TestRSIBB:
    def test_generate_signal(self):
        strat = RSIBBStrategy(rsi_length=7, bb_length=20, bb_std=2.0, rsi_oversold=30, rsi_overbought=70, squeeze_threshold=0.02)
        df = compute_indicators(_make_candle_df(100), rsi_length=7, bb_length=20, bb_std=2.0)
        signal, meta = strat.generate_signal(df)
        assert signal in (-1, 0, 1)

    def test_backtest_signal(self):
        strat = RSIBBStrategy()
        df = compute_indicators(_make_candle_df(200))
        trades = strat.backtest_signal(df)
        assert isinstance(trades, list)

    def test_params_dict(self):
        strat = RSIBBStrategy(rsi_length=7, bb_length=20, bb_std=2.0, rsi_oversold=30, rsi_overbought=70, squeeze_threshold=0.02)
        assert "rsi_length" in strat.params_dict()
        assert "squeeze_threshold" in strat.params_dict()


class TestVWAPCap:
    def test_generate_signal(self):
        strat = VWAPCapStrategy(vol_spike_min=2.0, vwap_revert_pct=0.001, vol_sma_length=20)
        df = compute_indicators(_make_candle_df(100), vol_sma_length=20)
        signal, meta = strat.generate_signal(df)
        assert signal in (-1, 0, 1)

    def test_backtest_signal(self):
        strat = VWAPCapStrategy()
        df = compute_indicators(_make_candle_df(200))
        trades = strat.backtest_signal(df)
        assert isinstance(trades, list)

    def test_params_dict(self):
        assert "vol_spike_min" in VWAPCapStrategy().params_dict()


class TestEMACross:
    def test_generate_signal(self):
        strat = EMACrossStrategy(ema_fast=5, ema_slow=13)
        df = compute_indicators(_make_candle_df(100), ema_fast=5, ema_slow=13)
        signal, meta = strat.generate_signal(df)
        assert signal in (-1, 0, 1)

    def test_backtest_signal(self):
        strat = EMACrossStrategy()
        df = compute_indicators(_make_candle_df(200))
        trades = strat.backtest_signal(df)
        assert isinstance(trades, list)

    def test_params_dict(self):
        assert EMACrossStrategy(ema_fast=8, ema_slow=21).params_dict() == {"ema_fast": 8, "ema_slow": 21}


def test_strategy_registry():
    from src.strategies import STRATEGY_REGISTRY
    assert set(STRATEGY_REGISTRY.keys()) == {"macd_hist", "rsi_bb", "vwap_cap", "ema_cross"}
