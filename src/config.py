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

    LOOP_INTERVAL: int = 3600

    model_config = {"env_file": ".env", "extra": "ignore"}
