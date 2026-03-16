"""Fetch historical resolved markets and train the XGBoost model."""
import json
import logging
import math
from datetime import datetime, timezone
import httpx
from src.predictor.xgb_model import PredictionModel, FEATURE_ORDER
from src.db import Database

logger = logging.getLogger(__name__)


async def fetch_resolved_markets(limit: int = 2000) -> list[dict]:
    """Fetch resolved (closed) markets from Gamma API with sufficient volume."""
    all_markets = []
    offset = 0
    batch_size = 100
    async with httpx.AsyncClient(timeout=30) as client:
        while len(all_markets) < limit:
            resp = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "closed": "true",
                    "limit": batch_size,
                    "offset": offset,
                    "order": "volumeNum",
                    "ascending": "false",
                },
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_markets.extend(batch)
            if len(batch) < batch_size:
                break
            offset += batch_size
    logger.info(f"Fetched {len(all_markets)} resolved markets")
    return all_markets[:limit]


def market_to_features(market: dict) -> dict | None:
    """Extract training features from a resolved market. Returns None if unusable."""
    try:
        prices = json.loads(market.get("outcomePrices", "[]"))
        if len(prices) < 2:
            return None

        yes_price = float(prices[0])
        no_price = float(prices[1])

        # Must be fully resolved (price at 0 or 1)
        if not (yes_price >= 0.99 or yes_price <= 0.01):
            return None

        volume = float(market.get("volumeNum", 0) or 0)
        liquidity = float(market.get("liquidityNum", 0) or 0)

        # Skip very low volume markets (noisy)
        if volume < 1000:
            return None

        spread = abs(1.0 - yes_price - no_price)
        daily_volume = volume / max(30, 1)  # Rough daily estimate

        # Use real market data — no synthetic price generation
        # For Gamma API fallback, we use volume/liquidity features only
        # (prices are resolved so they don't help for training)
        features = {
            "yes_price": 0.5,  # Unknown pre-resolution price, use neutral
            "no_price": 0.5,
            "spread": spread,
            "log_liquidity": math.log1p(liquidity),
            "log_volume_24h": math.log1p(daily_volume),
            "days_to_resolution": 30,  # Unknown for historical
            "volume_liquidity_ratio": daily_volume / max(liquidity, 1),
            "flag_wide_spread": 1 if spread > 0.10 else 0,
            "flag_high_volume": 1 if volume > 50000 else 0,
            "flag_price_spike": 0,
            # Neutral sentiment defaults (no historical sentiment available)
            "sentiment_positive_ratio": 0.33,
            "sentiment_negative_ratio": 0.33,
            "sentiment_neutral_ratio": 0.34,
            "sentiment_avg_score": 0.5,
            "sentiment_sample_size": 0,
            "sentiment_polarity": 0.0,
            "price_sentiment_gap": 0.0,
            "sentiment_convergence": 0.5,
            "narrative_alignment": 0.0,
            "has_research_data": 0,
            # Structured data defaults (no historical structured data available)
            "clob_bid_ask_spread": 0.0,
            "clob_buy_depth": 0.0,
            "clob_sell_depth": 0.0,
            "clob_imbalance": 0.5,
            "clob_midpoint_vs_gamma": 0.0,
            "crypto_price_usd": 0.0,
            "crypto_24h_change": 0.0,
            "crypto_market_cap": 0.0,
            "crypto_is_relevant": 0.0,
            "fred_cpi_latest": 0.0,
            "fred_fed_funds_rate": 0.0,
            "fred_unemployment": 0.0,
            "fred_is_relevant": 0.0,
        }

        # Label: 1 if YES won, 0 if NO won
        label = 1 if yes_price >= 0.99 else 0

        return {"features": features, "label": label, "volume": volume}

    except (json.JSONDecodeError, TypeError, ValueError):
        return None


async def train_from_history(db_path: str = "data/polymarket.db",
                             model_path: str = "model_xgb.json") -> PredictionModel:
    """Train XGB model on real settled trade data, fall back to Gamma API."""
    db = Database(db_path)
    db.init()

    conn = db._conn()
    rows = conn.execute("""
        SELECT p.features_json, p.market_yes_price, p.predicted_prob,
               t.resolved_outcome, t.side
        FROM predictions p
        JOIN trades t ON p.market_id = t.market_id
        WHERE t.status IN ('settled', 'dry_run_settled')
        AND t.resolved_outcome IS NOT NULL
        AND p.features_json IS NOT NULL
    """).fetchall()

    if len(rows) >= 10:
        logger.info(f"Training on {len(rows)} real settled trades")
        feature_dicts = []
        labels = []
        for row in rows:
            features = json.loads(row["features_json"])
            label = 1 if row["resolved_outcome"] == "YES" else 0
            feature_dicts.append(features)
            labels.append(label)

        # 80/20 train/test split for validation
        split_idx = int(len(feature_dicts) * 0.8)
        if split_idx < 8:
            split_idx = len(feature_dicts)  # too few for split, use all

        train_features = feature_dicts[:split_idx]
        train_labels = labels[:split_idx]
        test_features = feature_dicts[split_idx:]
        test_labels = labels[split_idx:]

        model = PredictionModel()
        model.train(train_features, train_labels)

        # Evaluate on test set if we have one
        if test_features:
            correct = 0
            brier_sum = 0.0
            for feat, actual in zip(test_features, test_labels):
                prob = model.predict(feat)
                if prob is not None:
                    predicted_class = 1 if prob > 0.5 else 0
                    if predicted_class == actual:
                        correct += 1
                    brier_sum += (prob - actual) ** 2
            accuracy = correct / len(test_features)
            brier = brier_sum / len(test_features)
            logger.info(
                f"Validation: accuracy={accuracy:.2%}, Brier={brier:.4f} "
                f"(n={len(test_features)}, random baseline: accuracy=50%, Brier=0.25)"
            )

        # Log feature importances
        _log_feature_importances(model)

        model.save(model_path)
        # Save model metadata for tracking degradation
        meta = {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "n_train": len(train_labels),
            "n_test": len(test_features),
            "accuracy": accuracy if test_features else None,
            "brier": brier if test_features else None,
            "yes_ratio": sum(train_labels) / len(train_labels),
            "feature_count": len(FEATURE_ORDER),
        }
        with open(model_path + ".meta.json", "w") as f:
            json.dump(meta, f, indent=2)
        logger.info(f"Model trained on {len(train_labels)} trades, saved to {model_path}")
        db.close()
        return model

    logger.warning(f"Only {len(rows)} real trades with features — falling back to Gamma API")
    db.close()
    return await _train_from_gamma_api(model_path)


def _log_feature_importances(model: PredictionModel):
    """Log XGBoost feature importances to help identify useful signals."""
    if model.model is None:
        return
    try:
        importances = model.model.feature_importances_
        pairs = sorted(zip(FEATURE_ORDER, importances), key=lambda x: x[1], reverse=True)
        top = pairs[:10]
        lines = [f"  {name}: {imp:.4f}" for name, imp in top]
        logger.info("Top feature importances:\n" + "\n".join(lines))
    except Exception as e:
        logger.debug(f"Could not log feature importances: {e}")


async def _train_from_gamma_api(model_path: str = "model_xgb.json") -> PredictionModel:
    """Fallback training from Gamma API resolved markets (no synthetic prices)."""
    markets = await fetch_resolved_markets(limit=2000)

    samples = []
    for m in markets:
        result = market_to_features(m)
        if result:
            samples.append(result)

    if len(samples) < 50:
        logger.warning(f"Only {len(samples)} usable Gamma API samples, need at least 50")
        return PredictionModel()

    samples.sort(key=lambda s: s["volume"], reverse=True)
    features = [s["features"] for s in samples]
    labels = [s["label"] for s in samples]

    yes_count = sum(labels)
    no_count = len(labels) - yes_count
    logger.info(f"Training on {len(samples)} Gamma markets (YES: {yes_count}, NO: {no_count})")

    model = PredictionModel()
    model.train(features, labels)
    _log_feature_importances(model)
    model.save(model_path)
    logger.info(f"Model saved to {model_path}")
    return model


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(train_from_history())
