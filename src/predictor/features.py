import math
import re
from src.models import ScannedMarket, ScanFlag


# --- Market type classification from question text ---
_SPREAD_PATTERNS = re.compile(
    r'spread|handicap|\([+-]\d+\.?\d*\)|cover', re.IGNORECASE
)
_TOTALS_PATTERNS = re.compile(
    r'\bO/U\b|\bover.?under\b|\btotal\b', re.IGNORECASE
)
_CRYPTO_PATTERNS = re.compile(
    r'\b(bitcoin|btc|ethereum|eth|solana|sol|crypto|doge)\b.*\b(price|reach|hit|dip|above|below)\b',
    re.IGNORECASE,
)
_SOCIAL_PATTERNS = re.compile(
    r'\b(tweet|post|follower|retweet|like)\b.*\b(count|number|reach|hit)\b',
    re.IGNORECASE,
)
_ESPORTS_PATTERNS = re.compile(
    r'\b(LoL|Dota|CS2|CSGO|Valorant|esport|LCK|LEC|LCS|LPL)\b', re.IGNORECASE
)
_POLITICS_PATTERNS = re.compile(
    r'\b(election|president|parliament|vote|governor|senate|congress|minister)\b',
    re.IGNORECASE,
)

# Data quality tier keywords (tier 1 = best, tier 4 = no-bet)
_TIER1_PATTERNS = re.compile(
    r'\b(NBA|NFL|Premier League|EPL|La Liga|Serie A|Bundesliga|Ligue 1|MLB|Champions League)\b',
    re.IGNORECASE,
)
_TIER2_PATTERNS = re.compile(
    r'\b(NHL|Primeira Liga|Eredivisie|MLS|Liga MX|World Cup|WBC|Olympics|NCAA)\b',
    re.IGNORECASE,
)
_TIER3_PATTERNS = re.compile(
    r'\b(Challenger|ITF|CBA|Patriot League|SWAC|Zadar)\b', re.IGNORECASE
)


def classify_market_type(question: str) -> int:
    """Classify market type from question text.

    Returns: 0=moneyline/win, 1=totals, 2=spread, 3=political,
             4=crypto, 5=social/behavioral, 6=esports
    """
    if _SOCIAL_PATTERNS.search(question):
        return 5
    if _CRYPTO_PATTERNS.search(question):
        return 4
    if _SPREAD_PATTERNS.search(question):
        return 2
    if _TOTALS_PATTERNS.search(question):
        return 1
    if _ESPORTS_PATTERNS.search(question):
        return 6
    if _POLITICS_PATTERNS.search(question):
        return 3
    return 0  # default: moneyline/win


def classify_data_quality_tier(question: str) -> int:
    """Classify data quality tier from question text.

    Returns: 1=top tier (major leagues), 2=mid tier, 3=low data, 4=no-bet domains
    """
    if _SOCIAL_PATTERNS.search(question):
        return 4
    if _CRYPTO_PATTERNS.search(question):
        return 4
    if _TIER3_PATTERNS.search(question):
        return 3
    if _ESPORTS_PATTERNS.search(question):
        return 3
    if _TIER1_PATTERNS.search(question):
        return 1
    if _TIER2_PATTERNS.search(question):
        return 2
    return 2  # default: mid-tier for unclassified


def extract_features(market: ScannedMarket, sentiment_agg: dict,
                     structured_data: dict | None = None,
                     prediction_context: dict | None = None) -> dict:
    """Extract features for XGBoost from market data and sentiment.

    Args:
        prediction_context: Optional dict with keys:
            - edge: float, the predicted edge
            - predicted_prob: float, the predicted probability
            - calibration_band_obs: int, count of prior settled predictions in same band
    """
    sd = structured_data or {}
    ctx = prediction_context or {}
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
        # CLOB features (5)
        "clob_bid_ask_spread": sd.get("clob_bid_ask_spread", 0.0),
        "clob_buy_depth": math.log1p(sd.get("clob_buy_depth", 0.0)),
        "clob_sell_depth": math.log1p(sd.get("clob_sell_depth", 0.0)),
        "clob_imbalance": sd.get("clob_imbalance", 0.5),
        "clob_midpoint_vs_gamma": sd.get("clob_midpoint_vs_gamma", 0.0),
        # CoinGecko features (4)
        "crypto_price_usd": math.log1p(sd.get("crypto_price_usd", 0.0)),
        "crypto_24h_change": sd.get("crypto_24h_change", 0.0),
        "crypto_market_cap": math.log1p(sd.get("crypto_market_cap", 0.0)),
        "crypto_is_relevant": sd.get("crypto_is_relevant", 0.0),
        # FRED features (4)
        "fred_cpi_latest": sd.get("fred_cpi_latest", 0.0),
        "fred_fed_funds_rate": sd.get("fred_fed_funds_rate", 0.0),
        "fred_unemployment": sd.get("fred_unemployment", 0.0),
        "fred_is_relevant": sd.get("fred_is_relevant", 0.0),
        # Lesson-derived features (4)
        "market_type": classify_market_type(market.question),
        "data_quality_tier": classify_data_quality_tier(market.question),
        "edge_anomaly_flag": _edge_anomaly_flag(ctx.get("edge"), ctx.get("predicted_prob")),
        "calibration_band_obs": ctx.get("calibration_band_obs", 0),
        # Sports data features (3)
        "rest_days_differential": sd.get("rest_days_differential", 0.0),
        "standings_pct_delta": sd.get("standings_pct_delta", 0.0),
        "sports_is_relevant": sd.get("sports_is_relevant", 0.0),
    }


def _edge_anomaly_flag(edge: float | None, prob: float | None) -> int:
    """Flag when claimed edge > 15% on a sub-60% probability prediction."""
    if edge is None or prob is None:
        return 0
    return 1 if abs(edge) > 0.15 and prob < 0.60 else 0
