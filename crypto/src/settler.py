import asyncio
import logging
from datetime import datetime, timezone
from src.db import Database
from src.scanner import CryptoScanner
from src.tracker import IncubationTracker
from src.config import Settings

logger = logging.getLogger(__name__)


def calc_crypto_pnl(entry_price: float, stake: float, won: bool, fee_pct: float = 0.02) -> float:
    fee = stake * fee_pct
    if won:
        return (1.0 / entry_price - 1.0) * stake - fee
    else:
        return -stake - fee


class CryptoSettler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.DB_PATH)
        self.db.init()
        self.scanner = CryptoScanner(gamma_url=settings.POLYMARKET_GAMMA_URL)
        scale_seq = [float(x) for x in settings.CRYPTO_SCALE_SEQUENCE.split(",")]
        self.tracker = IncubationTracker(
            db=self.db, scale_sequence=scale_seq,
            min_days=settings.CRYPTO_INCUBATION_MIN_DAYS,
            max_consecutive_loss_days=settings.CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS,
        )

    async def run(self):
        """Check and settle all open crypto trades."""
        trades = self.db.get_open_crypto_trades()
        if not trades:
            logger.debug("No open crypto trades to settle")
            return

        logger.info(f"Checking {len(trades)} open crypto trades")
        settled_count = 0
        for trade in trades:
            market_id = trade.get("market_id")
            token_id = trade.get("token_id")
            if not market_id:
                continue

            resolution = await self.scanner.check_resolution(market_id, token_id=token_id)
            if resolution is None:
                continue

            won = (trade["side"] == resolution)
            pnl = calc_crypto_pnl(
                entry_price=trade["entry_price"],
                stake=trade["amount"],
                won=won,
                fee_pct=self.settings.POLYMARKET_FEE,
            )

            expected = trade["status"]
            if expected == "dry_run_open":
                new_status = "dry_run_won" if won else "dry_run_lost"
            else:
                new_status = "won" if won else "lost"

            # Race condition guard
            updated = self.db.settle_crypto_trade(
                trade["id"], status=new_status, pnl=pnl, expected_status=expected,
            )
            if not updated:
                continue  # Already settled by bot

            self.tracker.update_after_trade(trade["strategy"], won=won, pnl=pnl)
            settled_count += 1
            logger.info(f"Settled: {trade['strategy']} {trade['side']} -> {resolution} P&L: ${pnl:.2f}")

        if settled_count:
            logger.info(f"Settled {settled_count} crypto trades")
            # Update daily PnL
            self._update_daily_pnl()

    def _update_daily_pnl(self):
        """Recompute today's crypto PnL and upsert to crypto_pnl_daily."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Get all trades settled today
        all_trades = self.db.get_settled_crypto_trades(limit=500)
        today_trades = [t for t in all_trades if t.get("resolved_at", "").startswith(today)]
        if not today_trades:
            return
        wins = sum(1 for t in today_trades if t["pnl"] and t["pnl"] > 0)
        losses = len(today_trades) - wins
        gross_pnl = sum(t["pnl"] for t in today_trades if t["pnl"])
        fees = sum(t["amount"] * self.settings.POLYMARKET_FEE for t in today_trades)
        net_pnl = gross_pnl  # fees already included in pnl calc
        self.db.upsert_crypto_pnl_daily(
            date=today, trades_count=len(today_trades), wins=wins, losses=losses,
            gross_pnl=round(gross_pnl, 2), fees=round(fees, 2), net_pnl=round(net_pnl, 2),
            bankroll=self.settings.CRYPTO_BANKROLL,
        )

    async def run_loop(self, interval: int = 300):
        """Run settler in a loop every `interval` seconds (default 5 min)."""
        logger.info(f"Crypto settler starting, interval={interval}s")
        while True:
            try:
                await self.run()
            except Exception as e:
                logger.error(f"Settler cycle error: {e}")
            await asyncio.sleep(interval)
