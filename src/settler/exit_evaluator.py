from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from src.pnl import calc_unrealised_pnl

logger = logging.getLogger(__name__)


@dataclass
class ExitDecision:
    trade_id: int
    reason: str
    pnl: float
    current_edge: float
    question: str


def evaluate_exit(
    position: dict,
    fee_rate: float = 0.02,
    stop_loss_pct: float = 0.40,
    negative_edge_threshold: float = -0.05,
    profit_lock_pct: float = 0.60,
    stale_days: int = 30,
    stale_edge_threshold: float = 0.02,
) -> ExitDecision | None:
    current_price = position.get("current_price")
    predicted_prob = position.get("predicted_prob")
    if current_price is None or predicted_prob is None:
        return None

    side = position["side"]
    amount = position["amount"]
    entry_price = position["price"]
    trade_id = position["id"]
    question = position.get("question") or position.get("market_id", "unknown")

    pnl = calc_unrealised_pnl(side, amount, entry_price, current_price, fee_rate)

    if side == "YES":
        raw_edge = predicted_prob - current_price
    else:
        raw_edge = current_price - predicted_prob
    edge_after_fees = raw_edge - (2 * fee_rate)

    # Rule 1: Stop loss
    if pnl < -(stop_loss_pct * amount):
        return ExitDecision(trade_id, "stop_loss", pnl, edge_after_fees, question)

    # Rule 2: Negative edge
    if edge_after_fees < negative_edge_threshold:
        return ExitDecision(trade_id, "negative_edge", pnl, edge_after_fees, question)

    # Rule 3: Profit lock
    if side == "YES":
        shares = amount / entry_price if entry_price > 0 else 0
    else:
        no_price = 1.0 - entry_price
        shares = amount / no_price if no_price > 0 else 0
    max_profit = shares * 1.0 - amount
    if max_profit > 0 and pnl > (profit_lock_pct * max_profit):
        return ExitDecision(trade_id, "profit_lock", pnl, edge_after_fees, question)

    # Rule 4: Stale position
    executed_at_str = position.get("executed_at")
    if executed_at_str:
        try:
            executed_at = datetime.fromisoformat(executed_at_str)
            if executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=timezone.utc)
            days_open = (datetime.now(timezone.utc) - executed_at).days
            if days_open > stale_days and edge_after_fees < stale_edge_threshold:
                return ExitDecision(trade_id, "stale_position", pnl, edge_after_fees, question)
        except (ValueError, TypeError):
            pass

    return None
