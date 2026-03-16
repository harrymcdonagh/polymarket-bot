import math
from src.models import ScannedMarket, ScanFlag


def extract_features(market: ScannedMarket, sentiment_agg: dict) -> dict:
    """Extract features for XGBoost from market data and sentiment."""
    pos = sentiment_agg.get("positive_ratio", 0)
    neg = sentiment_agg.get("negative_ratio", 0)
    neu = sentiment_agg.get("neutral_ratio", 0)
    avg_score = sentiment_agg.get("avg_score", 0)
    sample_size = sentiment_agg.get("sample_size", 0)

    # Sentiment polarity and derived
    polarity = pos - neg
    price_sentiment_gap = market.yes_price - pos

    # Sentiment convergence: how much do sources agree?
    # Low std dev across source scores = high convergence = more reliable signal
    source_scores = sentiment_agg.get("source_scores", [])
    if len(source_scores) >= 2:
        mean_score = sum(source_scores) / len(source_scores)
        sentiment_std = (sum((s - mean_score) ** 2 for s in source_scores) / len(source_scores)) ** 0.5
    else:
        sentiment_std = 0.5  # high uncertainty when few sources

    # Narrative-vs-odds alignment (how well does research narrative match market price)
    narrative_alignment = sentiment_agg.get("narrative_alignment", 0.0)

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
        "sentiment_positive_ratio": pos,
        "sentiment_negative_ratio": neg,
        "sentiment_neutral_ratio": neu,
        "sentiment_avg_score": avg_score,
        "sentiment_sample_size": math.log1p(sample_size),  # log transform instead of cap
        # Derived sentiment
        "sentiment_polarity": polarity,
        "price_sentiment_gap": price_sentiment_gap,
        # Research quality signals
        "sentiment_convergence": 1.0 - sentiment_std,  # 1 = all sources agree, 0 = total disagreement
        "narrative_alignment": narrative_alignment,  # -1 to +1
        "has_research_data": 1 if sample_size > 0 else 0,  # flag: did research return anything?
    }
