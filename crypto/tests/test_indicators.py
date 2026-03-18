import pytest
import pandas as pd
import numpy as np
from src.indicators import compute_indicators


def _make_candle_df(n=100):
    np.random.seed(42)
    base_price = 84000.0
    prices = base_price + np.cumsum(np.random.randn(n) * 10)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-03-18", periods=n, freq="1min", tz="UTC"),
        "open": prices,
        "high": prices + np.abs(np.random.randn(n) * 5),
        "low": prices - np.abs(np.random.randn(n) * 5),
        "close": prices + np.random.randn(n) * 3,
        "volume": np.random.randint(50, 500, n).astype(float),
    })
    return df


def test_compute_indicators_adds_columns():
    df = _make_candle_df(100)
    result = compute_indicators(df)
    expected_cols = [
        "macd", "macd_signal", "macd_hist",
        "rsi",
        "bb_upper", "bb_mid", "bb_lower", "bb_bandwidth",
        "vwap",
        "ema_fast", "ema_slow",
        "vol_sma", "vol_spike_ratio",
        "atr",
    ]
    for col in expected_cols:
        assert col in result.columns, f"Missing column: {col}"


def test_compute_indicators_custom_params():
    df = _make_candle_df(100)
    result = compute_indicators(df, macd_fast=8, macd_slow=21, macd_signal=5,
                                rsi_length=7, bb_length=20, bb_std=2.0,
                                ema_fast=3, ema_slow=10, vol_sma_length=20)
    assert "macd" in result.columns
    assert "rsi" in result.columns


def test_compute_indicators_preserves_original_columns():
    df = _make_candle_df(100)
    result = compute_indicators(df)
    for col in ["timestamp", "open", "high", "low", "close", "volume"]:
        assert col in result.columns


def test_compute_indicators_too_few_candles():
    df = _make_candle_df(10)
    result = compute_indicators(df)
    assert len(result) == 10
