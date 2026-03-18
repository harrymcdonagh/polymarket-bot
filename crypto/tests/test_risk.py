import pytest
from src.risk import CryptoRiskManager


def test_approved():
    rm = CryptoRiskManager(max_daily_loss=20.0, max_position_size=100.0)
    ok, reason = rm.check(daily_pnl=0.0, proposed_size=1.50, has_open_trade=False)
    assert ok is True
    assert reason == ""


def test_daily_loss_exceeded():
    rm = CryptoRiskManager(max_daily_loss=20.0, max_position_size=100.0)
    ok, reason = rm.check(daily_pnl=-21.0, proposed_size=1.50, has_open_trade=False)
    assert ok is False
    assert "daily loss" in reason.lower()


def test_has_open_trade():
    rm = CryptoRiskManager(max_daily_loss=20.0, max_position_size=100.0)
    ok, reason = rm.check(daily_pnl=0.0, proposed_size=1.50, has_open_trade=True)
    assert ok is False
    assert "open" in reason.lower()


def test_size_too_large():
    rm = CryptoRiskManager(max_daily_loss=20.0, max_position_size=100.0)
    ok, reason = rm.check(daily_pnl=0.0, proposed_size=200.0, has_open_trade=False)
    assert ok is False
    assert "size" in reason.lower() or "exceeds" in reason.lower()


def test_exact_daily_loss_limit():
    rm = CryptoRiskManager(max_daily_loss=20.0, max_position_size=100.0)
    ok, reason = rm.check(daily_pnl=-20.0, proposed_size=1.50, has_open_trade=False)
    assert ok is False  # exactly at limit should block
