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

    async def watch_settlement(self, trade_id: int, token_id: str):
        """Poll for market resolution and update trade status."""
        import asyncio
        import httpx

        while True:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"https://clob.polymarket.com/price",
                        params={"token_id": token_id, "side": "BUY"},
                    )
                    data = resp.json()
                    price = float(data.get("price", 0.5))

                    # If price hits 0 or 1, market has resolved
                    if price >= 0.99 or price <= 0.01:
                        trades = self.db.get_open_trades()
                        trade = next((t for t in trades if t["id"] == trade_id), None)
                        if trade:
                            won = (price >= 0.99 and trade["side"] == "YES") or \
                                  (price <= 0.01 and trade["side"] == "NO")
                            pnl = trade["amount"] * (1 / trade["price"] - 1) if won else -trade["amount"]
                            self.db.update_trade_status(trade_id, "settled", pnl)
                            logger.info(f"Trade {trade_id} settled: PnL=${pnl:.2f}")
                        return

            except Exception as e:
                logger.warning(f"Settlement watch error: {e}")

            await asyncio.sleep(300)  # check every 5 minutes
