import logging

logger = logging.getLogger(__name__)


class CryptoRiskManager:
    def __init__(self, max_daily_loss: float = 20.0, max_position_size: float = 100.0):
        self.max_daily_loss = max_daily_loss
        self.max_position_size = max_position_size

    def check(self, daily_pnl: float, proposed_size: float, has_open_trade: bool) -> tuple[bool, str]:
        """Pre-trade risk check. Returns (allowed, reason)."""
        if daily_pnl <= -self.max_daily_loss:
            return False, f"Daily loss limit reached (PnL: ${daily_pnl:.2f})"
        if proposed_size > self.max_position_size:
            return False, f"Position size ${proposed_size:.2f} exceeds max ${self.max_position_size:.2f}"
        if has_open_trade:
            return False, "Already has open crypto trade"
        return True, ""
