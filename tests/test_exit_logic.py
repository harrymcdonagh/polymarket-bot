import pytest
from datetime import datetime, timezone, timedelta
from src.settler.exit_evaluator import evaluate_exit, ExitDecision
from src.pnl import calc_unrealised_pnl


def _make_position(side="YES", amount=50.0, entry_price=0.40, current_price=0.50,
                    predicted_prob=0.60, days_ago=5):
    executed_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "id": 1, "market_id": "test-market", "side": side, "amount": amount,
        "price": entry_price, "current_price": current_price,
        "predicted_prob": predicted_prob, "executed_at": executed_at,
        "status": "dry_run", "question": "Test market?",
    }


def test_no_exit_when_edge_healthy():
    pos = _make_position(predicted_prob=0.60, current_price=0.50)
    result = evaluate_exit(pos, fee_rate=0.02)
    assert result is None


def test_stop_loss_triggers():
    pos = _make_position(entry_price=0.40, current_price=0.15)
    result = evaluate_exit(pos, fee_rate=0.02, stop_loss_pct=0.40)
    assert result is not None
    assert result.reason == "stop_loss"
    assert result.pnl < 0


def test_negative_edge_triggers():
    pos = _make_position(predicted_prob=0.50, current_price=0.60)
    result = evaluate_exit(pos, fee_rate=0.02, negative_edge_threshold=-0.05)
    assert result is not None
    assert result.reason == "negative_edge"


def test_profit_lock_triggers():
    pos = _make_position(entry_price=0.20, current_price=0.85, predicted_prob=0.90)
    result = evaluate_exit(pos, fee_rate=0.02, profit_lock_pct=0.60)
    assert result is not None
    assert result.reason == "profit_lock"
    assert result.pnl > 0


def test_stale_position_triggers():
    pos = _make_position(predicted_prob=0.52, current_price=0.50, days_ago=35)
    result = evaluate_exit(pos, fee_rate=0.02, stale_days=30, stale_edge_threshold=0.02)
    assert result is not None
    assert result.reason == "stale_position"


def test_stale_position_does_not_trigger_if_edge_healthy():
    pos = _make_position(predicted_prob=0.65, current_price=0.50, days_ago=35)
    result = evaluate_exit(pos, fee_rate=0.02, stale_days=30, stale_edge_threshold=0.02)
    assert result is None


def test_stop_loss_priority_over_negative_edge():
    pos = _make_position(entry_price=0.40, current_price=0.10, predicted_prob=0.30)
    result = evaluate_exit(pos, fee_rate=0.02, stop_loss_pct=0.40, negative_edge_threshold=-0.05)
    assert result is not None
    assert result.reason == "stop_loss"


def test_no_side_edge_calculation():
    pos = _make_position(side="NO", predicted_prob=0.70, current_price=0.80, entry_price=0.70)
    result = evaluate_exit(pos, fee_rate=0.02)
    assert result is None

    pos2 = _make_position(side="NO", predicted_prob=0.70, current_price=0.55, entry_price=0.70)
    result2 = evaluate_exit(pos2, fee_rate=0.02, negative_edge_threshold=-0.05)
    assert result2 is not None
    assert result2.reason == "negative_edge"


def test_skips_missing_data():
    pos = _make_position()
    pos["current_price"] = None
    result = evaluate_exit(pos, fee_rate=0.02)
    assert result is None

    pos2 = _make_position()
    pos2["predicted_prob"] = None
    result2 = evaluate_exit(pos2, fee_rate=0.02)
    assert result2 is None
