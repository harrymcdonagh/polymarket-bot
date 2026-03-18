import json
import pytest
from src.config import Settings


def test_crypto_defaults():
    s = Settings(CRYPTO_ENABLED=False)
    assert s.CRYPTO_ENABLED is False
    assert s.CRYPTO_POSITION_SIZE == 1.50
    assert s.CRYPTO_MAX_POSITION_SIZE == 100.0
    assert s.CRYPTO_STRATEGY == "macd_hist"
    assert s.CRYPTO_SYMBOL == "BTC"
    assert s.CRYPTO_TRADE_INTERVAL == 300
    assert s.CRYPTO_CANDLE_WINDOW == 100
    assert s.CRYPTO_MAX_CONCURRENT_TRADES == 1
    assert s.CRYPTO_INCUBATION_MIN_DAYS == 14
    assert s.CRYPTO_SCALE_SEQUENCE == "1.50,5,10,25,50,100"
    assert s.CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS == 3


def test_crypto_strategy_params_valid():
    s = Settings(
        CRYPTO_STRATEGY="macd_hist",
        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}',
    )
    assert s.CRYPTO_STRATEGY_PARAMS == '{"macd_fast":3,"macd_slow":15,"macd_signal":3}'


def test_crypto_strategy_params_invalid_json():
    with pytest.raises(Exception):
        Settings(CRYPTO_STRATEGY_PARAMS="not json")


def test_crypto_position_size_range():
    with pytest.raises(Exception):
        Settings(CRYPTO_POSITION_SIZE=-1.0)
