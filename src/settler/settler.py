import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
import httpx
from src.db import Database
from src.notifications.telegram import TelegramNotifier

if TYPE_CHECKING:
    from src.postmortem.postmortem import PostmortemAnalyzer

logger = logging.getLogger(__name__)


class Settler:
    def __init__(self, db: Database, notifier: TelegramNotifier,
                 gamma_url: str = "https://gamma-api.polymarket.com",
                 postmortem: "PostmortemAnalyzer | None" = None):
        self.db = db
        self.notifier = notifier
        self.gamma_url = gamma_url
        self.postmortem = postmortem
        self._last_summary_date: str | None = None

    async def check_resolution(self, condition_id: str) -> str | None:
        """Check if a market has resolved. Returns 'YES'/'NO' or None if still active."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{self.gamma_url}/markets/{condition_id}")
                if resp.status_code != 200:
                    logger.warning(f"Gamma API returned {resp.status_code} for {condition_id}")
                    return None
                # Support both sync (real httpx) and async (test mocks) .json()
                raw = resp.json()
                data = (await raw) if hasattr(raw, "__await__") else raw

            if not data.get("resolved", False):
                return None

            prices_str = data.get("outcomePrices", "[]")
            prices = json.loads(prices_str)
            if len(prices) >= 2:
                yes_price = float(prices[0])
                return "YES" if yes_price > 0.5 else "NO"
            return None
        except Exception as e:
            logger.warning(f"Resolution check failed for {condition_id}: {e}")
            return None

    def calc_hypothetical_pnl(self, side: str, amount: float, price: float,
                              outcome: str) -> float:
        """Calculate what the P&L would have been.

        On Polymarket, buying shares at price P means you get (amount/P) shares.
        If your side wins, each share pays $1. If it loses, shares are worth $0.
        Note: price stored is always yes_price. For NO trades, NO share price = 1 - yes_price.
        """
        if side == "YES":
            shares = amount / price
            if outcome == "YES":
                return shares * 1.0 - amount
            else:
                return -amount
        else:  # NO
            no_share_price = 1.0 - price
            shares = amount / no_share_price
            if outcome == "NO":
                return shares * 1.0 - amount
            else:
                return -amount

    async def run(self) -> None:
        """Check all unresolved dry-run trades and settle any that have resolved."""
        trades = self.db.get_unresolved_dry_run_trades()
        if not trades:
            logger.info("No unresolved dry-run trades to check")
            return

        logger.info(f"Checking {len(trades)} unresolved dry-run trades")

        for trade in trades:
            outcome = await self.check_resolution(trade["market_id"])
            if outcome is None:
                continue

            pnl = self.calc_hypothetical_pnl(
                side=trade["side"],
                amount=trade["amount"],
                price=trade["price"],
                outcome=outcome,
            )

            self.db.settle_dry_run_trade(
                trade_id=trade["id"],
                resolved_outcome=outcome,
                hypothetical_pnl=pnl,
            )

            logger.info(
                f"Settled: {trade['market_id'][:20]} -> {outcome} | "
                f"Hypothetical P&L: ${pnl:.2f}"
            )

            # Run postmortem on losses
            if pnl < 0 and self.postmortem:
                try:
                    await self.postmortem.analyze_loss(
                        question=trade["market_id"],
                        predicted_prob=trade.get("predicted_prob", 0.5),
                        actual_outcome=outcome,
                        pnl=pnl,
                        reasoning="Dry-run trade — see trade history",
                    )
                except Exception as e:
                    logger.error(f"Postmortem failed for trade {trade['id']}: {e}")

            # Notify
            if self.notifier.is_enabled:
                msg = self.notifier.format_settlement_alert(
                    question=trade["market_id"],
                    outcome=outcome,
                    predicted_prob=trade.get("predicted_prob", 0.5),
                    price=trade["price"],
                    pnl=pnl,
                )
                await self.notifier.send(msg)

        await self._maybe_send_daily_summary()

    async def _maybe_send_daily_summary(self) -> None:
        """Send daily summary if it hasn't been sent today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_summary_date == today:
            return
        if not self.notifier.is_enabled:
            return

        stats = self.db.get_trade_stats()
        dry_run_count = self.db.get_dry_run_trade_count()

        msg = (
            f"*Daily Summary ({today})*\n"
            f"Dry-run trades: {dry_run_count}\n"
            f"Settled: {stats['total_trades']} | Win rate: {stats['win_rate']:.0%}\n"
            f"Total P&L: ${stats['total_pnl']:.2f}"
        )
        await self.notifier.send(msg)
        self._last_summary_date = today
