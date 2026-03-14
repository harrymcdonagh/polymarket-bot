from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Polymarket
    POLYMARKET_PRIVATE_KEY: str = ""
    POLYMARKET_FUNDER_ADDRESS: str = ""
    POLYMARKET_CLOB_URL: str = "https://clob.polymarket.com"
    POLYMARKET_GAMMA_URL: str = "https://gamma-api.polymarket.com"
    POLYMARKET_DATA_URL: str = "https://data-api.polymarket.com"

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # Reddit
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "polymarket-bot/1.0"

    # Risk parameters
    MAX_BET_FRACTION: float = 0.05
    MIN_EDGE_THRESHOLD: float = 0.08
    CONFIDENCE_THRESHOLD: float = 0.7
    MAX_DAILY_LOSS: float = 100.0
    BANKROLL: float = 1000.0

    # Scanner parameters
    MIN_LIQUIDITY: float = 5000.0
    MIN_VOLUME_24H: float = 1000.0
    MAX_DAYS_TO_RESOLUTION: int = 90
    SPREAD_ALERT_THRESHOLD: float = 0.10
    PRICE_MOVE_ALERT_THRESHOLD: float = 0.15

    # Model hyperparameters
    XGB_N_ESTIMATORS: int = 100
    XGB_MAX_DEPTH: int = 4
    XGB_LEARNING_RATE: float = 0.1

    # Research limits
    RSS_ENTRY_LIMIT: int = 20
    SENTIMENT_AMBIGUITY_THRESHOLD: float = 0.6

    # Operational
    LOG_LEVEL: str = "INFO"
    LOOP_INTERVAL: int = 300

    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator("BANKROLL")
    @classmethod
    def bankroll_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("BANKROLL must be positive")
        return v

    @field_validator("MAX_BET_FRACTION")
    @classmethod
    def bet_fraction_range(cls, v: float) -> float:
        if not 0 < v <= 1:
            raise ValueError("MAX_BET_FRACTION must be between 0 and 1")
        return v

    @field_validator("CONFIDENCE_THRESHOLD")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError("CONFIDENCE_THRESHOLD must be between 0 and 1")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def valid_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return v.upper()
