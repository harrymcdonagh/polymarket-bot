import pytest
from src.pnl import calc_unrealised_pnl


def test_yes_side_price_up():
    # Bought YES at $0.40 for $10. Current price $0.60.
    # Shares = 10 / 0.40 = 25. Value = 25 * 0.60 = 15.
    # Fee = 10 * 0.02 = 0.20. PnL = 15 - 10 - 0.20 = 4.80
    pnl = calc_unrealised_pnl(side="YES", amount=10.0, entry_price=0.40, current_yes_price=0.60)
    assert pnl == pytest.approx(4.80)


def test_yes_side_price_down():
    pnl = calc_unrealised_pnl(side="YES", amount=10.0, entry_price=0.60, current_yes_price=0.40)
    assert pnl == pytest.approx(-3.5333, abs=0.01)


def test_no_side_price_down_is_profit():
    pnl = calc_unrealised_pnl(side="NO", amount=10.0, entry_price=0.70, current_yes_price=0.50)
    assert pnl == pytest.approx(6.4667, abs=0.01)


def test_no_side_price_up_is_loss():
    pnl = calc_unrealised_pnl(side="NO", amount=10.0, entry_price=0.50, current_yes_price=0.70)
    assert pnl == pytest.approx(-4.20)


def test_guard_entry_price_zero():
    pnl = calc_unrealised_pnl(side="YES", amount=10.0, entry_price=0.0, current_yes_price=0.50)
    assert pnl == pytest.approx(-10.0)


def test_guard_entry_price_one():
    pnl = calc_unrealised_pnl(side="NO", amount=10.0, entry_price=1.0, current_yes_price=0.50)
    assert pnl == pytest.approx(-10.0)


def test_custom_fee_rate():
    pnl = calc_unrealised_pnl(side="YES", amount=10.0, entry_price=0.40, current_yes_price=0.60, fee_rate=0.0)
    assert pnl == pytest.approx(5.0)
