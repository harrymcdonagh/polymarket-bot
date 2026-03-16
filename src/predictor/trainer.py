"""Fetch historical resolved markets and train the XGBoost model."""
import json
import logging
import math
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

        # Use actual market characteristics the model can learn from.
        # We sample yes_price from a distribution around the base rate
        # to give the model varied price inputs rather than a constant.
        import random
        base_rate = 0.5
        simulated_yes = base_rate + random.gauss(0, 0.15)
        simulated_yes = max(0.05, min(0.95, simulated_yes))

        features = {
            "yes_price": simulated_yes,
            "no_price": 1.0 - simulated_yes,
            "spread": spread,
            "log_liquidity": math.log1p(liquidity),
            "log_volume_24h": math.log1p(daily_volume),
            "days_to_resolution": 30,  # Unknown for historical, use default
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
            "price_sentiment_gap": simulated_yes - 0.33,
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

        model = PredictionModel()
        model.train(feature_dicts, labels)
        model.save(model_path)
        logger.info(f"Model trained on {len(labels)} real trades, saved to {model_path}")
        db.close()
        return model

    logger.warning(f"Only {len(rows)} real trades with features — falling back to Gamma API")
    db.close()
    return await _train_from_gamma_api(model_path)


async def _train_from_gamma_api(model_path: str = "model_xgb.json") -> PredictionModel:
    """Original training from Gamma API resolved markets."""
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
    model.save(model_path)
    logger.info(f"Model saved to {model_path}")
    return model


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(train_from_history())
