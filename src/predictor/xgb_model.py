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
        """Train XGBoost on historical data."""
        X = np.array([[fd.get(f, 0.0) for f in FEATURE_ORDER] for fd in feature_dicts])
        y = np.array(labels)
        self.model = xgb.XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            objective="binary:logistic",
            eval_metric="logloss",
        )
        self.model.fit(X, y)
        logger.info("XGBoost model trained on %d samples", len(labels))

    def predict(self, features: dict) -> float:
        """Return predicted probability of YES outcome."""
        if self.model is None:
            # No trained model: return market price as baseline
            return features.get("yes_price", 0.5)
        X = self._features_to_array(features)
        return float(self.model.predict_proba(X)[0][1])

    def save(self, path: str = "model_xgb.json"):
        if self.model:
            self.model.save_model(path)

    def load(self, path: str = "model_xgb.json"):
        self.model = xgb.XGBClassifier()
        self.model.load_model(path)
