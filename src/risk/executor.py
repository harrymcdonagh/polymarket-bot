import logging
from datetime import datetime, timezone
from src.models import TradeDecision, TradeExecution
from src.db import Database

logger = logging.getLogger(__name__)


class TradeExecutor:
    def __init__(self, clob_client, db: Database):
        self.clob = clob_client
        self.db = db

    def execute(self, decision: TradeDecision, token_id: str) -> TradeExecution:
        """Place a trade on Polymarket via the CLOB API."""
        now = datetime.now(timezone.utc)

        if not decision.approved:
            return TradeExecution(
                market_id=decision.market_id,
                decision=decision,
                side=decision.prediction.recommended_side,
                amount_usd=0,
                price=decision.prediction.market_yes_price,
                status="rejected",
                executed_at=now,
            )

        try:
            # Build order using py-clob-client
            from py_clob_client.order_builder.constants import BUY

            order_args = {
                "token_id": token_id,
                "price": round(decision.prediction.market_yes_price, 2),
                "size": round(decision.bet_size_usd / decision.prediction.market_yes_price, 2),
                "side": BUY,
            }
            response = self.clob.create_and_post_order(order_args)
            order_id = response.get("orderID", response.get("order_id", "unknown"))

            logger.info(f"Order placed: {order_id} | {decision.prediction.recommended_side} ${decision.bet_size_usd}")

            # Save to DB
            self.db.save_trade(
                market_id=decision.market_id,
                side=decision.prediction.recommended_side,
                amount=decision.bet_size_usd,
                price=decision.prediction.market_yes_price,
                order_id=order_id,
            )

            return TradeExecution(
                market_id=decision.market_id,
                decision=decision,
                order_id=order_id,
                side=decision.prediction.recommended_side,
                amount_usd=decision.bet_size_usd,
                price=decision.prediction.market_yes_price,
                status="pending",
                executed_at=now,
            )

        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            return TradeExecution(
                market_id=decision.market_id,
                decision=decision,
                side=decision.prediction.recommended_side,
                amount_usd=decision.bet_size_usd,
                price=decision.prediction.market_yes_price,
                status="failed",
                executed_at=now,
            )

    def sell(self, trade: dict, current_price: float) -> dict:
        """Place a SELL order to exit a position.

        Args:
            trade: dict with keys: id, market_id, side, amount, price (entry yes_price)
            current_price: current YES market price

        Returns:
            dict with keys: success (bool), order_id (str|None), fill_price (float|None)
        """
        try:
            from py_clob_client.order_builder.constants import SELL

            side = trade["side"]
            amount = trade["amount"]
            entry_price = trade["price"]

            if side == "YES":
                token_id = trade.get("token_yes_id", "")
                shares = amount / entry_price if entry_price > 0 else 0
                sell_price = round(current_price * 0.995, 2)
            else:
                token_id = trade.get("token_no_id", "")
                no_entry_price = 1.0 - entry_price
                shares = amount / no_entry_price if no_entry_price > 0 else 0
                sell_price = round((1.0 - current_price) * 0.995, 2)

            if not token_id or shares <= 0 or sell_price <= 0:
                logger.warning(f"Cannot sell trade {trade['id']}: invalid params")
                return {"success": False, "order_id": None, "fill_price": None}

            order_args = {
                "token_id": token_id,
                "price": sell_price,
                "size": round(shares, 2),
                "side": SELL,
            }
            response = self.clob.create_and_post_order(order_args)
            order_id = response.get("orderID", response.get("order_id", "unknown"))
            logger.info(f"SELL order placed: {order_id} | trade {trade['id']} | {shares:.2f} shares @ ${sell_price}")

            return {"success": True, "order_id": order_id, "fill_price": sell_price}

        except Exception as e:
            logger.error(f"SELL order failed for trade {trade['id']}: {e}")
            return {"success": False, "order_id": None, "fill_price": None}

    async def watch_settlement(self, trade_id: int, token_id: str, max_checks: int = 2016):
        """Poll for market resolution and update trade status.

        Args:
            max_checks: Max poll attempts (default 2016 = ~7 days at 5min intervals).
        """
        import asyncio
        import httpx

        base_interval = 300  # 5 minutes
        backoff_multiplier = 1
        checks = 0

        while checks < max_checks:
            checks += 1
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        "https://gamma-api.polymarket.com/markets",
                        params={"clob_token_ids": token_id, "limit": 1},
                    )
                    resp.raise_for_status()
                    markets = resp.json()

                    if not markets:
                        logger.debug(f"Settlement watch {trade_id}: market not found")
                        await asyncio.sleep(base_interval * backoff_multiplier)
                        continue

                    market = markets[0]
                    closed = market.get("closed", False)
                    if closed in (True, "true"):
                        trades = self.db.get_open_trades()
                        trade = next((t for t in trades if t["id"] == trade_id), None)
                        if trade:
                            # Check resolved outcome prices
                            import json
                            prices = json.loads(market.get("outcomePrices", "[]"))
                            if len(prices) >= 2:
                                resolved_yes = float(prices[0])
                            else:
                                resolved_yes = 0.5

                            won = (resolved_yes >= 0.99 and trade["side"] == "YES") or \
                                  (resolved_yes <= 0.01 and trade["side"] == "NO")
                            # PnL: winning = amount * (1/price - 1), losing = -amount
                            pnl = trade["amount"] * (1.0 / trade["price"] - 1.0) if won else -trade["amount"]
                            self.db.update_trade_status(trade_id, "settled", pnl)
                            logger.info(f"Trade {trade_id} settled: {'WON' if won else 'LOST'} PnL=${pnl:.2f}")
                        return

                # Reset backoff on successful check
                backoff_multiplier = 1

            except Exception as e:
                logger.warning(f"Settlement watch error for trade {trade_id}: {e}")
                backoff_multiplier = min(backoff_multiplier * 2, 12)  # max 1 hour

            await asyncio.sleep(base_interval * backoff_multiplier)

        logger.warning(f"Settlement watch for trade {trade_id} timed out after {max_checks} checks")
