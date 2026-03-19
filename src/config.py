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
    CONFIDENCE_THRESHOLD: float = 0.5
    MAX_DAILY_LOSS: float = 100.0
    BANKROLL: float = 1000.0
    POLYMARKET_FEE: float = 0.02

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

    # Research source weights
    NEWSAPI_KEY: str = ""
    SOURCE_WEIGHT_NEWSAPI: float = 1.0
    SOURCE_WEIGHT_RSS_MAJOR: float = 0.9
    SOURCE_WEIGHT_RSS_PREDICTION: float = 0.8
    SOURCE_WEIGHT_RSS_GOOGLE: float = 0.7
    SOURCE_WEIGHT_TWITTER: float = 0.5
    SOURCE_WEIGHT_REDDIT: float = 0.6
    SOURCE_WEIGHT_GOOGLE_TRENDS: float = 0.6
    SOURCE_WEIGHT_METACULUS: float = 0.9
    SOURCE_WEIGHT_PREDICTIT: float = 0.85
    SOURCE_WEIGHT_WIKIPEDIA: float = 0.7

    # Sentiment LLM
    SENTIMENT_MODEL: str = "claude-haiku-4-5-20251001"
    SENTIMENT_USE_LLM: bool = True
    SENTIMENT_LLM_THRESHOLD: float = 0.4

    # Metaculus API
    METACULUS_API_TOKEN: str = ""

    # FRED API
    FRED_API_KEY: str = ""

    # Sports data
    BALLDONTLIE_API_KEY: str = ""

    # Sharp odds
    ODDSPAPI_API_KEY: str = ""

    RESEARCH_TIMEOUT: int = 30
    RESEARCH_CONCURRENCY: int = 5  # max markets researched in parallel

    # LLM model names
    CALIBRATION_MODEL: str = "claude-sonnet-4-6"
    NARRATIVE_MODEL: str = "claude-haiku-4-5-20251001"
    POSTMORTEM_MODEL: str = "claude-sonnet-4-6"

    # Operational
    LOG_LEVEL: str = "INFO"
    LOOP_INTERVAL: int = 14400  # full pipeline cycle (4 hours)
    SETTLEMENT_INTERVAL: int = 7200  # settlement + postmortem check (2 hours)

    # Database
    DB_PATH: str = "data/polymarket.db"

    # Telegram notifications
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Dashboard security
    DASHBOARD_PASSWORD: str = ""

    # Crypto 5-min module
    CRYPTO_ENABLED: bool = False
    CRYPTO_POSITION_SIZE: float = 1.50
    CRYPTO_MAX_POSITION_SIZE: float = 100.0
    CRYPTO_STRATEGY: str = "macd_hist"
    CRYPTO_STRATEGY_PARAMS: str = '{"macd_fast":3,"macd_slow":15,"macd_signal":3}'
    CRYPTO_SYMBOL: str = "BTC"
    CRYPTO_TRADE_INTERVAL: int = 300
    CRYPTO_CANDLE_WINDOW: int = 100
    CRYPTO_MAX_CONCURRENT_TRADES: int = 1
    CRYPTO_INCUBATION_MIN_DAYS: int = 14
    CRYPTO_SCALE_SEQUENCE: str = "1.50,5,10,25,50,100"
    CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS: int = 3

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

    @field_validator(
        "SOURCE_WEIGHT_NEWSAPI", "SOURCE_WEIGHT_RSS_MAJOR",
        "SOURCE_WEIGHT_RSS_PREDICTION", "SOURCE_WEIGHT_RSS_GOOGLE",
        "SOURCE_WEIGHT_TWITTER", "SOURCE_WEIGHT_REDDIT",
        "SOURCE_WEIGHT_GOOGLE_TRENDS",
        "SOURCE_WEIGHT_METACULUS", "SOURCE_WEIGHT_PREDICTIT", "SOURCE_WEIGHT_WIKIPEDIA",
    )
    @classmethod
    def weight_range(cls, v: float) -> float:
        if not 0 < v <= 1:
            raise ValueError("Source weight must be between 0 (exclusive) and 1 (inclusive)")
        return v
