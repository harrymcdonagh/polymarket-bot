import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
import httpx
from src.db import Database
from src.notifications.telegram import TelegramNotifier
from src.pnl import calc_unrealised_pnl

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
        self._last_positions_update: str | None = None

    async def _fetch_markets_for_ids(self, condition_ids: set[str]) -> dict[str, dict]:
        """Fetch market data using clob_token_ids for targeted lookups.

        The Gamma API ignores the conditionId query param, but supports
        clob_token_ids. We look up token IDs from market_snapshots, then
        query each market directly.
        Returns a dict mapping conditionId -> market data.
        """
        found: dict[str, dict] = {}
        # Get token ID mapping from DB (populated by the scanner)
        token_map = self.db.get_token_ids_for_conditions(condition_ids)
        missing = len(condition_ids) - len(token_map)
        if missing:
            logger.warning(f"Missing token IDs for {missing} markets — scanner needs to run first")

        if not token_map:
            logger.warning("No token IDs found — cannot fetch market data")
            return found

        logger.info(f"Found token IDs for {len(token_map)}/{len(condition_ids)} markets")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                for cid, token_id in token_map.items():
                    try:
                        resp = await client.get(
                            f"{self.gamma_url}/markets",
                            params={"clob_token_ids": token_id, "limit": 1},
                        )
                        if resp.status_code == 429:
                            logger.warning("Rate limited, waiting 5s...")
                            await asyncio.sleep(5)
                            resp = await client.get(
                                f"{self.gamma_url}/markets",
                                params={"clob_token_ids": token_id, "limit": 1},
                            )
                        if resp.status_code != 200:
                            continue
                        raw = resp.json()
                        results = (await raw) if hasattr(raw, "__await__") else raw
                        if isinstance(results, list) and results:
                            found[cid] = results[0]
                        elif isinstance(results, dict) and results:
                            found[cid] = results
                        await asyncio.sleep(0.1)  # Throttle: 10 req/s
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"Market fetch error: {e}")
        return found

    def _parse_resolution(self, data: dict) -> str | None:
        """Check if a market has resolved or closed. Returns 'YES'/'NO' or None.

        Polymarket markets go closed (no more trading) before resolved
        (official settlement). We treat closed as settled since the
        outcome prices are already at 0/1 by that point.
        """
        resolved = data.get("resolved", False)
        closed = data.get("closed", False)
        if not resolved and not closed:
            return None

        prices_str = data.get("outcomePrices", "[]")
        try:
            prices = json.loads(prices_str)
        except (json.JSONDecodeError, TypeError):
            return None
        if len(prices) >= 2:
            yes_price = float(prices[0])
            if yes_price > 0.5:
                return "YES"
            elif yes_price < 0.5:
                return "NO"
            else:
                logger.warning(f"Market resolved with ambiguous 0.5 price, skipping")
        return None

    async def check_resolution(self, condition_id: str) -> str | None:
        """Check if a single market has resolved. Returns 'YES'/'NO' or None.

        Note: The Gamma API ignores the conditionId query param, so this
        falls back to paginated search. Prefer using _fetch_markets_for_ids
        for bulk lookups.
        """
        markets = await self._fetch_markets_for_ids({condition_id})
        data = markets.get(condition_id)
        if data is None:
            logger.debug(f"No market found for conditionId {condition_id}")
            return None
        return self._parse_resolution(data)

    def calc_hypothetical_pnl(self, side: str, amount: float, price: float,
                              outcome: str, fee_rate: float = 0.02) -> float:
        """Calculate what the P&L would have been, net of Polymarket fees.

        On Polymarket, buying shares at price P means you get (amount/P) shares.
        If your side wins, each share pays $1. If it loses, shares are worth $0.
        Note: price stored is always yes_price. For NO trades, NO share price = 1 - yes_price.
        Fee is charged on entry (buy) amount.
        """
        fee = amount * fee_rate
        if side == "YES":
            shares = amount / price
            if outcome == "YES":
                return shares * 1.0 - amount - fee
            else:
                return -amount - fee
        else:  # NO
            no_share_price = 1.0 - price
            shares = amount / no_share_price
            if outcome == "NO":
                return shares * 1.0 - amount - fee
            else:
                return -amount - fee

    async def refresh_open_positions(self) -> None:
        """Refresh current prices for all open positions via bulk Gamma API."""
        trades = self.db.get_open_positions_with_prices()
        if not trades:
            return

        market_ids = {t["market_id"] for t in trades}

        # Fetch live market data (paginated scan)
        market_data = await self._fetch_markets_for_ids(market_ids)

        # Extract prices from market data (include 0 and 1 for closed markets)
        prices: dict[str, float] = {}
        for cid, data in market_data.items():
            try:
                outcome = json.loads(data.get("outcomePrices", "[]"))
                if len(outcome) >= 2:
                    p = float(outcome[0])
                    if 0 <= p <= 1:
                        prices[cid] = p
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        # Fill gaps from DB snapshots (for markets not in current active listing)
        for market_id in market_ids:
            if market_id not in prices:
                snap_price = self.db.get_latest_snapshot_price(market_id)
                if snap_price is not None and 0 <= snap_price <= 1:
                    prices[market_id] = snap_price

        logger.info(f"Got prices for {len(prices)}/{len(market_ids)} markets")

        # Update DB and build position summaries
        positions = []
        for trade in trades:
            current_price = prices.get(trade["market_id"])
            if current_price is None:
                continue
            self.db.update_trade_price(trade["id"], current_price)
            pnl = calc_unrealised_pnl(
                side=trade["side"],
                amount=trade["amount"],
                entry_price=trade["price"],
                current_yes_price=current_price,
            )
            question = trade.get("question") or trade["market_id"]
            positions.append({
                "question": question,
                "side": trade["side"],
                "price": trade["price"],
                "current_price": current_price,
                "unrealised_pnl": pnl,
            })

        if not positions:
            return

        total_unrealised = sum(p["unrealised_pnl"] for p in positions)
        logger.info(f"Refreshed {len(positions)} positions, total unrealised: ${total_unrealised:.2f}")

        # Save PnL snapshot for charting
        stats = self.db.get_trade_stats()
        settled_pnl = stats["total_pnl"]
        self.db.save_pnl_snapshot(
            settled_pnl=settled_pnl,
            unrealised_pnl=round(total_unrealised, 2),
            total_pnl=round(settled_pnl + total_unrealised, 2),
            open_positions=len(positions),
        )

        # Throttle Telegram updates to once per 6 hours
        now = datetime.now(timezone.utc)
        should_send = True
        if self._last_positions_update:
            last = datetime.fromisoformat(self._last_positions_update)
            if (now - last).total_seconds() < 6 * 3600:
                should_send = False

        if should_send and self.notifier.is_enabled:
            msg = self.notifier.format_positions_update(positions, total_unrealised)
            await self.notifier.send(msg)
            self._last_positions_update = now.isoformat()

    async def run(self) -> None:
        """Check all unresolved dry-run trades and settle any that have resolved."""
        trades = self.db.get_unresolved_dry_run_trades()
        if not trades:
            logger.info("No unresolved dry-run trades to check")
            # Still refresh positions for price updates
            await self.refresh_open_positions()
            return

        # Fetch all market data in one bulk scan (covers both price refresh + resolution)
        all_market_ids = {t["market_id"] for t in trades}
        open_positions = self.db.get_open_positions_with_prices()
        all_market_ids.update(t["market_id"] for t in open_positions)

        logger.info(f"Fetching market data for {len(all_market_ids)} markets")
        market_data = await self._fetch_markets_for_ids(all_market_ids)
        logger.info(f"Found data for {len(market_data)}/{len(all_market_ids)} markets")

        # --- Price refresh using fetched data ---
        prices: dict[str, float] = {}
        for cid, data in market_data.items():
            try:
                outcome = json.loads(data.get("outcomePrices", "[]"))
                if len(outcome) >= 2:
                    p = float(outcome[0])
                    if 0 <= p <= 1:
                        prices[cid] = p
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        if open_positions:
            position_ids = {t["market_id"] for t in open_positions}
            for market_id in position_ids:
                if market_id not in prices:
                    snap_price = self.db.get_latest_snapshot_price(market_id)
                    if snap_price is not None and 0 <= snap_price <= 1:
                        prices[market_id] = snap_price

            logger.info(f"Got prices for {len(prices)}/{len(position_ids)} markets")
            positions = []
            for trade in open_positions:
                current_price = prices.get(trade["market_id"])
                if current_price is None:
                    continue
                self.db.update_trade_price(trade["id"], current_price)
                pnl = calc_unrealised_pnl(
                    side=trade["side"],
                    amount=trade["amount"],
                    entry_price=trade["price"],
                    current_yes_price=current_price,
                )
                question = trade.get("question") or trade["market_id"]
                positions.append({
                    "question": question,
                    "side": trade["side"],
                    "price": trade["price"],
                    "current_price": current_price,
                    "unrealised_pnl": pnl,
                })

            if positions:
                total_unrealised = sum(p["unrealised_pnl"] for p in positions)
                logger.info(f"Refreshed {len(positions)} positions, total unrealised: ${total_unrealised:.2f}")
                stats = self.db.get_trade_stats()
                settled_pnl = stats["total_pnl"]
                self.db.save_pnl_snapshot(
                    settled_pnl=settled_pnl,
                    unrealised_pnl=round(total_unrealised, 2),
                    total_pnl=round(settled_pnl + total_unrealised, 2),
                    open_positions=len(positions),
                )

                now = datetime.now(timezone.utc)
                should_send = True
                if self._last_positions_update:
                    last = datetime.fromisoformat(self._last_positions_update)
                    if (now - last).total_seconds() < 6 * 3600:
                        should_send = False
                if should_send and self.notifier.is_enabled:
                    msg = self.notifier.format_positions_update(positions, total_unrealised)
                    await self.notifier.send(msg)
                    self._last_positions_update = now.isoformat()

        # --- Settlement using fetched data ---
        logger.info(f"Checking {len(trades)} unresolved dry-run trades")

        for trade in trades:
            data = market_data.get(trade["market_id"])
            if data is None:
                continue

            outcome = self._parse_resolution(data)
            if outcome is None:
                continue

            # Resolve human-readable question
            question = trade["market_id"]
            snapshot_question = self.db.get_market_question(trade["market_id"])
            if snapshot_question:
                question = snapshot_question

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

            # Save rule-based metrics
            was_correct = (trade["side"] == outcome)
            pred = self.db.get_prediction_for_market(trade["market_id"])
            self.db.save_trade_metric(
                trade_id=trade["id"],
                market_id=trade["market_id"],
                predicted_prob=trade.get("predicted_prob"),
                actual_outcome=outcome,
                predicted_side=trade["side"],
                was_correct=was_correct,
                edge_at_entry=pred.get("edge") if pred else None,
                confidence_at_entry=pred.get("confidence") if pred else None,
                hypothetical_pnl=pnl,
                market_yes_price=trade["price"],
            )

            logger.info(
                f"Settled: {question[:60]} -> {outcome} | "
                f"Hypothetical P&L: ${pnl:.2f}"
            )

            # LLM postmortem only on high-confidence wrong predictions
            if not was_correct:
                if pred and abs(pred.get("edge", 0)) > 0.05 and self.postmortem:
                    try:
                        await self.postmortem.analyze_loss(
                            question=question,
                            predicted_prob=trade.get("predicted_prob", 0.5),
                            actual_outcome=outcome,
                            pnl=pnl,
                            reasoning=f"Edge was {pred['edge']:.2%}, confidence {pred['confidence']:.2f}",
                            predicted_side=trade["side"],
                            was_correct=was_correct,
                        )
                    except Exception as e:
                        logger.error(f"Postmortem failed for trade {trade['id']}: {e}")

            # Notify
            if self.notifier.is_enabled:
                msg = self.notifier.format_settlement_alert(
                    question=question,
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
        pred_stats = self.db.get_prediction_stats()
        accuracy = self.db.get_prediction_accuracy()
        daily_pnl = self.db.get_daily_pnl()
        snapshots = self.db.get_snapshot_count()

        acc_str = f"{accuracy['accuracy']:.0%} ({accuracy['correct']}/{accuracy['evaluated']})" if accuracy['evaluated'] > 0 else "No resolved trades yet"

        msg = (
            f"*Daily Summary ({today})*\n\n"
            f"*Predictions:* {pred_stats['total_predictions']} total\n"
            f"  Approved: {pred_stats['approved']} | Blocked: {pred_stats['blocked']}\n"
            f"  Avg confidence: {pred_stats['avg_confidence']:.2f}\n"
            f"  Avg edge: {pred_stats['avg_edge']:.2%}\n\n"
            f"*Trades:* {dry_run_count} dry-run\n"
            f"  Settled: {stats['settled_trades']} | Win rate: {stats['win_rate']:.0%}\n"
            f"  Accuracy: {acc_str}\n\n"
            f"*P&L:* Today ${daily_pnl:.2f} | Total ${stats['total_pnl']:.2f}\n"
            f"*Snapshots:* {snapshots}"
        )
        open_positions = self.db.get_open_positions_with_prices()
        if open_positions:
            total_unrealised = sum(
                calc_unrealised_pnl(
                    side=t["side"], amount=t["amount"],
                    entry_price=t["price"], current_yes_price=t["current_price"],
                )
                for t in open_positions if t.get("current_price") is not None
            )
            ur_str = f"+${total_unrealised:.2f}" if total_unrealised >= 0 else f"-${abs(total_unrealised):.2f}"
            msg += f"\n*Open positions:* {len(open_positions)} | Unrealised {ur_str}"

        await self.notifier.send(msg)
        self._last_summary_date = today
