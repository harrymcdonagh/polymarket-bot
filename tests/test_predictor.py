import pytest
import numpy as np
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
from src.predictor.features import extract_features
from src.predictor.xgb_model import PredictionModel
from src.predictor.calibrator import Calibrator
from src.models import ScannedMarket, ScanFlag, ResearchReport, SentimentResult


def test_extract_features_returns_dict():
    market = ScannedMarket(
        condition_id="0xabc",
        question="Will X happen?",
        slug="will-x-happen",
        token_yes_id="tok_yes",
        token_no_id="tok_no",
        yes_price=0.60,
        no_price=0.40,
        spread=0.02,
        liquidity=50000,
        volume_24h=10000,
        end_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
        days_to_resolution=20,
        flags=[ScanFlag.HIGH_VOLUME],
        scanned_at=datetime.now(timezone.utc),
    )
    sentiment_agg = {
        "positive_ratio": 0.6,
        "negative_ratio": 0.2,
        "neutral_ratio": 0.2,
        "avg_score": 0.65,
        "sample_size": 50,
    }
    features = extract_features(market, sentiment_agg)
    assert "yes_price" in features
    assert "sentiment_positive_ratio" in features
    assert "log_liquidity" in features
    assert features["yes_price"] == 0.60


def test_model_predict_returns_probability():
    model = PredictionModel()
    features = {
        "yes_price": 0.5, "no_price": 0.5, "spread": 0.02,
        "log_liquidity": 10.0, "log_volume_24h": 8.0,
        "days_to_resolution": 30, "volume_liquidity_ratio": 0.2,
        "flag_wide_spread": 0, "flag_high_volume": 0, "flag_price_spike": 0,
        "sentiment_positive_ratio": 0.5, "sentiment_negative_ratio": 0.3,
        "sentiment_neutral_ratio": 0.2, "sentiment_avg_score": 0.5,
        "sentiment_sample_size": 50, "sentiment_polarity": 0.2,
        "price_sentiment_gap": 0.0,
    }
    prob = model.predict(features)
    assert 0.0 <= prob <= 1.0


def test_model_train_and_predict():
    model = PredictionModel()
    # Create synthetic training data
    X = [
        {"yes_price": 0.3, "sentiment_polarity": -0.4, "log_liquidity": 9, "log_volume_24h": 7,
         "spread": 0.05, "no_price": 0.7, "days_to_resolution": 10, "volume_liquidity_ratio": 0.1,
         "flag_wide_spread": 0, "flag_high_volume": 0, "flag_price_spike": 0,
         "sentiment_positive_ratio": 0.2, "sentiment_negative_ratio": 0.6,
         "sentiment_neutral_ratio": 0.2, "sentiment_avg_score": 0.3,
         "sentiment_sample_size": 30, "price_sentiment_gap": 0.1},
        {"yes_price": 0.8, "sentiment_polarity": 0.5, "log_liquidity": 11, "log_volume_24h": 9,
         "spread": 0.01, "no_price": 0.2, "days_to_resolution": 5, "volume_liquidity_ratio": 0.3,
         "flag_wide_spread": 0, "flag_high_volume": 1, "flag_price_spike": 0,
         "sentiment_positive_ratio": 0.7, "sentiment_negative_ratio": 0.1,
         "sentiment_neutral_ratio": 0.2, "sentiment_avg_score": 0.8,
         "sentiment_sample_size": 100, "price_sentiment_gap": 0.1},
    ] * 10  # need more samples
    y = [0] * 10 + [1] * 10
    model.train(X, y)
    # High sentiment + high price -> should predict higher prob
    prob = model.predict(X[10])
    assert prob >= 0.5


def test_trainer_market_to_features_valid():
    from src.predictor.trainer import market_to_features
    market = {
        "outcomePrices": '["1.0", "0.0"]',
        "volumeNum": 100000,
        "liquidityNum": 50000,
    }
    result = market_to_features(market)
    assert result is not None
    assert result["label"] == 1
    assert "features" in result
    assert len(result["features"]) == 17


def test_trainer_market_to_features_rejects_unresolved():
    from src.predictor.trainer import market_to_features
    market = {
        "outcomePrices": '["0.60", "0.40"]',
        "volumeNum": 100000,
        "liquidityNum": 50000,
    }
    result = market_to_features(market)
    assert result is None


def test_trainer_market_to_features_rejects_low_volume():
    from src.predictor.trainer import market_to_features
    market = {
        "outcomePrices": '["1.0", "0.0"]',
        "volumeNum": 500,
        "liquidityNum": 50000,
    }
    result = market_to_features(market)
    assert result is None


def test_trainer_market_to_features_no_outcome():
    from src.predictor.trainer import market_to_features
    market = {
        "outcomePrices": '["0.99"]',
        "volumeNum": 100000,
        "liquidityNum": 50000,
    }
    result = market_to_features(market)
    assert result is None


def test_model_save_and_load(tmp_path):
    model = PredictionModel()
    X = [
        {"yes_price": 0.3, "sentiment_polarity": -0.4, "log_liquidity": 9, "log_volume_24h": 7,
         "spread": 0.05, "no_price": 0.7, "days_to_resolution": 10, "volume_liquidity_ratio": 0.1,
         "flag_wide_spread": 0, "flag_high_volume": 0, "flag_price_spike": 0,
         "sentiment_positive_ratio": 0.2, "sentiment_negative_ratio": 0.6,
         "sentiment_neutral_ratio": 0.2, "sentiment_avg_score": 0.3,
         "sentiment_sample_size": 30, "price_sentiment_gap": 0.1},
    ] * 10
    y = [0] * 5 + [1] * 5
    model.train(X, y)
    path = str(tmp_path / "test_model.json")
    model.save(path)

    loaded = PredictionModel()
    loaded.load(path)
    prob = loaded.predict(X[0])
    assert 0.0 <= prob <= 1.0


@pytest.mark.asyncio
async def test_calibrator_combines_xgb_and_llm():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"probability": 0.65, "reasoning": "Strong evidence supports YES"}')]

    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=mock_response)

    calibrator = Calibrator(anthropic_client=mock_client)

    market = ScannedMarket(
        condition_id="0xabc", question="Will X happen?", slug="x",
        token_yes_id="ty", token_no_id="tn",
        yes_price=0.50, no_price=0.50, spread=0.02,
        liquidity=50000, volume_24h=10000,
        end_date=None, days_to_resolution=30,
        flags=[], scanned_at=datetime.now(timezone.utc),
    )
    research = ResearchReport(
        market_id="0xabc", question="Will X happen?",
        sentiments=[], narrative_summary="Mixed signals",
        narrative_vs_odds_alignment=0.0, researched_at=datetime.now(timezone.utc),
    )

    prediction = await calibrator.calibrate(
        market=market, research=research, xgb_probability=0.60
    )
    assert prediction.predicted_probability > 0
    assert prediction.confidence > 0
    assert prediction.reasoning != ""
