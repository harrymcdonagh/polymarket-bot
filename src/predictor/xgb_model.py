import logging
import numpy as np
import xgboost as xgb

logger = logging.getLogger(__name__)

FEATURE_ORDER = [
    "yes_price", "no_price", "spread", "log_liquidity", "log_volume_24h",
    "days_to_resolution", "volume_liquidity_ratio",
    "flag_wide_spread", "flag_high_volume", "flag_price_spike",
    "sentiment_positive_ratio", "sentiment_negative_ratio",
    "sentiment_neutral_ratio", "sentiment_avg_score", "sentiment_sample_size",
    "sentiment_polarity", "price_sentiment_gap",
    "sentiment_convergence", "narrative_alignment", "has_research_data",
    # CLOB order book (5)
    "clob_bid_ask_spread", "clob_buy_depth", "clob_sell_depth",
    "clob_imbalance", "clob_midpoint_vs_gamma",
    # CoinGecko crypto (4)
    "crypto_price_usd", "crypto_24h_change", "crypto_market_cap",
    "crypto_is_relevant",
    # FRED economic (4)
    "fred_cpi_latest", "fred_fed_funds_rate", "fred_unemployment",
    "fred_is_relevant",
    # Lesson-derived (4)
    "market_type", "data_quality_tier", "edge_anomaly_flag",
    "calibration_band_obs",
    # Sports data (3)
    "rest_days_differential", "standings_pct_delta", "sports_is_relevant",
]


class PredictionModel:
    def __init__(self, model_path: str | None = None):
        self.model: xgb.XGBClassifier | None = None
        if model_path:
            self.load(model_path)

    def _features_to_array(self, features: dict) -> np.ndarray:
        return np.array([[features.get(f, 0.0) for f in FEATURE_ORDER]])

    def train(self, feature_dicts: list[dict], labels: list[int],
              n_estimators: int = 100, max_depth: int = 4, learning_rate: float = 0.1):
        """Train XGBoost on historical data with automatic class balancing."""
        X = np.array([[fd.get(f, 0.0) for f in FEATURE_ORDER] for fd in feature_dicts])
        y = np.array(labels)
        # Handle class imbalance: weight minority class higher
        pos_count = int(y.sum())
        neg_count = len(y) - pos_count
        scale_pos = neg_count / max(pos_count, 1) if pos_count < neg_count else 1.0
        self.model = xgb.XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            objective="binary:logistic",
            eval_metric="logloss",
            scale_pos_weight=scale_pos,
        )
        self.model.fit(X, y)
        logger.info("XGBoost model trained on %d samples (YES=%d, NO=%d, scale_pos_weight=%.2f)",
                     len(labels), pos_count, neg_count, scale_pos)

    def predict(self, features: dict) -> float | None:
        """Return predicted probability of YES outcome, or None if no model."""
        if self.model is None:
            return None
        X = self._features_to_array(features)
        return float(self.model.predict_proba(X)[0][1])

    def save(self, path: str = "model_xgb.json"):
        if self.model:
            self.model.save_model(path)

    def load(self, path: str = "model_xgb.json"):
        self.model = xgb.XGBClassifier()
        self.model.load_model(path)
