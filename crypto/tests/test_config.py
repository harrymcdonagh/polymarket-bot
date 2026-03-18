import pytest
from src.config import Settings


def test_defaults():
    s = Settings(DB_PATH="data/test.db")
    assert s.CRYPTO_BANKROLL == 100.0
    assert s.CRYPTO_MAX_DAILY_LOSS == 20.0
    assert s.CRYPTO_POSITION_SIZE == 1.50
    assert s.CRYPTO_MAX_POSITION_SIZE == 100.0
    assert s.CRYPTO_STRATEGY == "macd_hist"
    assert s.CRYPTO_SYMBOL == "BTC"
    assert s.CRYPTO_CANDLE_WINDOW == 100
    assert s.CRYPTO_INCUBATION_MIN_DAYS == 14
    assert s.CRYPTO_SCALE_SEQUENCE == "1.50,5,10,25,50,100"
    assert s.CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS == 3
    assert s.POLYMARKET_FEE == 0.02


def test_strategy_params_valid():
    s = Settings(
        DB_PATH="data/test.db",
        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}',
    )
    assert s.CRYPTO_STRATEGY_PARAMS == '{"macd_fast":3,"macd_slow":15,"macd_signal":3}'


def test_strategy_params_invalid_json():
    with pytest.raises(Exception):
        Settings(DB_PATH="data/test.db", CRYPTO_STRATEGY_PARAMS="not json")


def test_position_size_positive():
    with pytest.raises(Exception):
        Settings(DB_PATH="data/test.db", CRYPTO_POSITION_SIZE=-1.0)


def test_bankroll_positive():
    with pytest.raises(Exception):
        Settings(DB_PATH="data/test.db", CRYPTO_BANKROLL=0)
