import math
from src.models import ScannedMarket, ScanFlag


def extract_features(market: ScannedMarket, sentiment_agg: dict) -> dict:
    """Extract features for XGBoost from market data and sentiment."""
    return {
        # Market features
        "yes_price": market.yes_price,
        "no_price": market.no_price,
        "spread": market.spread,
        "log_liquidity": math.log1p(market.liquidity),
        "log_volume_24h": math.log1p(market.volume_24h),
        "days_to_resolution": market.days_to_resolution or 0,
        "volume_liquidity_ratio": market.volume_24h / max(market.liquidity, 1),
        # Flags as binary features
        "flag_wide_spread": 1 if ScanFlag.WIDE_SPREAD in market.flags else 0,
        "flag_high_volume": 1 if ScanFlag.HIGH_VOLUME in market.flags else 0,
        "flag_price_spike": 1 if ScanFlag.PRICE_SPIKE in market.flags else 0,
        # Sentiment features
        "sentiment_positive_ratio": sentiment_agg.get("positive_ratio", 0),
        "sentiment_negative_ratio": sentiment_agg.get("negative_ratio", 0),
        "sentiment_neutral_ratio": sentiment_agg.get("neutral_ratio", 0),
        "sentiment_avg_score": sentiment_agg.get("avg_score", 0),
        "sentiment_sample_size": min(sentiment_agg.get("sample_size", 0), 200),  # cap
        # Derived
        "sentiment_polarity": sentiment_agg.get("positive_ratio", 0) - sentiment_agg.get("negative_ratio", 0),
        "price_sentiment_gap": market.yes_price - sentiment_agg.get("positive_ratio", 0),
    }
