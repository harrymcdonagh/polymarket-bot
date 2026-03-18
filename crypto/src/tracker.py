import logging
from datetime import datetime, timezone
from src.db import Database

logger = logging.getLogger(__name__)

DEFAULT_SCALE_SEQUENCE = [1.50, 5, 10, 25, 50, 100]


class IncubationTracker:
    def __init__(self, db: Database, scale_sequence: list[float] | None = None,
                 min_days: int = 14, max_consecutive_loss_days: int = 3):
        self.db = db
        self.scale_sequence = scale_sequence or DEFAULT_SCALE_SEQUENCE
        self.min_days = min_days
        self.max_consecutive_loss_days = max_consecutive_loss_days

    def update_after_trade(self, strategy: str, won: bool, pnl: float):
        """Update incubation record after a settled trade."""
        inc = self.db.get_or_create_incubation(strategy)
        total = inc["total_trades"] + 1
        wins = inc["wins"] + (1 if won else 0)
        losses = inc["losses"] + (0 if won else 1)
        total_pnl = round(inc["total_pnl"] + pnl, 2)
        self.db.update_incubation(strategy, total, wins, losses, total_pnl)

    def get_current_size(self, strategy: str) -> float:
        inc = self.db.get_or_create_incubation(strategy)
        return inc["position_size"]

    def check_scale_up(self, strategy: str) -> float | None:
        """Check if strategy qualifies for scaling up. Returns new size or None."""
        inc = self.db.get_or_create_incubation(strategy)
        if inc["status"] != "incubating":
            return None
        started = datetime.fromisoformat(inc["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - started).days
        if days < self.min_days:
            return None
        if inc["total_pnl"] <= 0:
            return None
        current = inc["position_size"]
        for i, size in enumerate(self.scale_sequence):
            if abs(size - current) < 0.01 and i + 1 < len(self.scale_sequence):
                new_size = self.scale_sequence[i + 1]
                self.db.update_incubation(
                    strategy, inc["total_trades"], inc["wins"], inc["losses"],
                    inc["total_pnl"], position_size=new_size, status="scaled",
                )
                return new_size
        return None

    def check_retire(self, strategy: str) -> bool:
        """Check if strategy should be retired due to consecutive losing days."""
        pnl_history = self.db.get_crypto_pnl_history()
        if len(pnl_history) < self.max_consecutive_loss_days:
            return False
        recent = pnl_history[-self.max_consecutive_loss_days:]
        if all(day["net_pnl"] < 0 for day in recent):
            inc = self.db.get_or_create_incubation(strategy)
            self.db.update_incubation(
                strategy, inc["total_trades"], inc["wins"], inc["losses"],
                inc["total_pnl"], status="retired",
            )
            return True
        return False
