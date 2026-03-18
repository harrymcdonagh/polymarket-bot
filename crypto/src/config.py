import json
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Polymarket
    POLYMARKET_PRIVATE_KEY: str = ""
    POLYMARKET_FUNDER_ADDRESS: str = ""
    POLYMARKET_CLOB_URL: str = "https://clob.polymarket.com"
    POLYMARKET_GAMMA_URL: str = "https://gamma-api.polymarket.com"

    # Database (shared with event bot)
    DB_PATH: str = "../data/polymarket.db"

    # Crypto bot settings
    CRYPTO_BANKROLL: float = 100.0
    CRYPTO_MAX_DAILY_LOSS: float = 20.0
    CRYPTO_POSITION_SIZE: float = 1.50
    CRYPTO_MAX_POSITION_SIZE: float = 100.0
    CRYPTO_STRATEGY: str = "macd_hist"
    CRYPTO_STRATEGY_PARAMS: str = '{"macd_fast":3,"macd_slow":15,"macd_signal":3}'
    CRYPTO_SYMBOL: str = "BTC"
    CRYPTO_CANDLE_WINDOW: int = 100
    CRYPTO_INCUBATION_MIN_DAYS: int = 14
    CRYPTO_SCALE_SEQUENCE: str = "1.50,5,10,25,50,100"
    CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS: int = 3
    POLYMARKET_FEE: float = 0.02

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator("CRYPTO_STRATEGY_PARAMS")
    @classmethod
    def valid_strategy_params(cls, v: str) -> str:
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError("CRYPTO_STRATEGY_PARAMS must be valid JSON")
        return v

    @field_validator("CRYPTO_POSITION_SIZE")
    @classmethod
    def position_size_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("CRYPTO_POSITION_SIZE must be positive")
        return v

    @field_validator("CRYPTO_BANKROLL")
    @classmethod
    def bankroll_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("CRYPTO_BANKROLL must be positive")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def valid_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return v.upper()
