import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from src.risk.risk_manager import RiskManager
from src.risk.executor import TradeExecutor
from src.models import Prediction, TradeDecision
from src.config import Settings
from src.db import Database


def _make_prediction(edge=0.10, confidence=0.8, yes_price=0.50, predicted_prob=0.60):
    return Prediction(
        market_id="0xabc",
        question="Test?",
        market_yes_price=yes_price,
        predicted_probability=predicted_prob,
        xgb_probability=predicted_prob,
        llm_probability=predicted_prob,
        edge=edge,
        confidence=confidence,
        recommended_side="YES",
        reasoning="test",
        predicted_at=datetime.now(timezone.utc),
    )


def test_kelly_fraction_positive_edge():
    settings = Settings(ANTHROPIC_API_KEY="test", BANKROLL=1000)
    rm = RiskManager(settings)
    # edge=0.10, price=0.50 -> kelly = (0.10 * 0.50) / (1 - 0.50) = 0.10
    fraction = rm._kelly_fraction(edge=0.10, price=0.50)
    assert 0.05 < fraction < 0.20


def test_risk_blocks_low_confidence():
    settings = Settings(ANTHROPIC_API_KEY="test", CONFIDENCE_THRESHOLD=0.7)
    rm = RiskManager(settings)
    prediction = _make_prediction(confidence=0.5)
    decision = rm.evaluate(prediction, daily_pnl=0)
    assert decision.approved is False
    assert "confidence" in decision.rejection_reason.lower()


def test_risk_blocks_low_edge():
    settings = Settings(ANTHROPIC_API_KEY="test", MIN_EDGE_THRESHOLD=0.08)
    rm = RiskManager(settings)
    prediction = _make_prediction(edge=0.03)
    decision = rm.evaluate(prediction, daily_pnl=0)
    assert decision.approved is False


def test_risk_approves_good_trade():
    settings = Settings(ANTHROPIC_API_KEY="test", BANKROLL=1000, MAX_BET_FRACTION=0.05)
    rm = RiskManager(settings)
    prediction = _make_prediction(edge=0.15, confidence=0.85)
    decision = rm.evaluate(prediction, daily_pnl=0)
    assert decision.approved is True
    assert 0 < decision.bet_size_usd <= 50  # max 5% of 1000


def test_risk_blocks_after_daily_loss_limit():
    settings = Settings(ANTHROPIC_API_KEY="test", MAX_DAILY_LOSS=100)
    rm = RiskManager(settings)
    prediction = _make_prediction(edge=0.15, confidence=0.85)
    decision = rm.evaluate(prediction, daily_pnl=-105)
    assert decision.approved is False
    assert "daily loss" in decision.rejection_reason.lower()


def test_executor_places_order(tmp_path):
    mock_clob = MagicMock()
    mock_clob.create_and_post_order.return_value = {"orderID": "order_abc123"}

    db = Database(str(tmp_path / "test.db"))
    db.init()

    executor = TradeExecutor(clob_client=mock_clob, db=db)
    prediction = _make_prediction(edge=0.15, confidence=0.85)

    trade_decision = TradeDecision(
        market_id="0xabc",
        prediction=prediction,
        approved=True,
        bet_size_usd=50.0,
        kelly_fraction=0.05,
        risk_score=0.5,
        decided_at=datetime.now(timezone.utc),
    )

    result = executor.execute(
        decision=trade_decision,
        token_id="tok_yes",
    )
    assert result.order_id == "order_abc123"
    assert result.status == "pending"
    # Verify trade was saved to DB
    trades = db.get_open_trades()
    assert len(trades) == 1
