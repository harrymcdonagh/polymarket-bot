import asyncio
import json
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.db import Database
from src.data_feed import CryptoDataFeed
from src.indicators import compute_indicators
from src.scanner import CryptoScanner
from src.risk import CryptoRiskManager
from src.tracker import IncubationTracker
from src.strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)


def is_5min_boundary(dt: datetime) -> bool:
    return dt.minute % 5 == 0


def calc_crypto_pnl(entry_price: float, stake: float, won: bool, fee_pct: float = 0.02) -> float:
    fee = stake * fee_pct
    if won:
        return (1.0 / entry_price - 1.0) * stake - fee
    else:
        return -stake - fee


class CryptoBot:
    def __init__(self, settings: Settings, dry_run: bool = True):
        self.settings = settings
        self.dry_run = dry_run
        self.db = Database(settings.DB_PATH)
        self.db.init()
        self.feed = CryptoDataFeed()
        self.scanner = CryptoScanner(gamma_url=settings.POLYMARKET_GAMMA_URL)
        self.risk_manager = CryptoRiskManager(
            max_daily_loss=settings.CRYPTO_MAX_DAILY_LOSS,
            max_position_size=settings.CRYPTO_MAX_POSITION_SIZE,
        )
        scale_seq = [float(x) for x in settings.CRYPTO_SCALE_SEQUENCE.split(",")]
        self.tracker = IncubationTracker(
            db=self.db, scale_sequence=scale_seq,
            min_days=settings.CRYPTO_INCUBATION_MIN_DAYS,
            max_consecutive_loss_days=settings.CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS,
        )
        self.strategy_name = settings.CRYPTO_STRATEGY
        params = json.loads(settings.CRYPTO_STRATEGY_PARAMS)
        strat_class = STRATEGY_REGISTRY.get(self.strategy_name)
        if strat_class is None:
            raise ValueError(f"Unknown strategy: {self.strategy_name}")
        self.strategy = strat_class(**params)
        self.indicator_params = params
        self._consecutive_errors = 0
        self._max_errors = 5
        self._clob_client = None

    async def run(self):
        """Main loop: run cycle every 60 seconds."""
        logger.info(f"Crypto bot starting: strategy={self.strategy_name} dry_run={self.dry_run}")
        while True:
            try:
                await self._run_cycle()
                self._consecutive_errors = 0
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(f"Cycle error ({self._consecutive_errors}/{self._max_errors}): {e}")
                if self._consecutive_errors >= self._max_errors:
                    logger.critical(f"Stopping after {self._max_errors} consecutive errors")
                    break
            await asyncio.sleep(60)
        await self.feed.close()

    async def _run_cycle(self):
        now = datetime.now(timezone.utc)
        # 1. Settle open trades
        await self._settle_open_trades()
        # 2. Only trade at 5-min boundaries
        if not is_5min_boundary(now):
            logger.debug(f"Not at 5-min boundary ({now.strftime('%H:%M')}), skipping")
            return
        logger.info(f"5-min boundary hit at {now.strftime('%H:%M:%S')} UTC")
        # 3. Fetch candles
        symbol = f"{self.settings.CRYPTO_SYMBOL}/USDT"
        df = await self.feed.fetch_candles(symbol, limit=self.settings.CRYPTO_CANDLE_WINDOW)
        if df is None:
            logger.warning("No candle data returned")
            return
        logger.info(f"Fetched {len(df)} candles, latest close: ${df['close'].iloc[-1]:.2f}")
        # 4. Compute indicators + signal
        enriched = compute_indicators(df, **self.indicator_params)
        signal, meta = self.strategy.generate_signal(enriched)
        logger.info(f"Signal: {signal} ({['NO TRADE', 'UP', 'DOWN'][signal] if signal in (0,1,-1) else signal}) | {meta}")
        if signal == 0:
            return
        # 5. Risk check
        daily_pnl = self.db.get_crypto_daily_pnl()
        open_trades = self.db.get_open_crypto_trades()
        size = self.tracker.get_current_size(self.strategy_name)
        ok, reason = self.risk_manager.check(daily_pnl, size, len(open_trades) > 0)
        if not ok:
            logger.info(f"Risk blocked: {reason}")
            return
        # 6. Find market
        market = await self.scanner.find_active_5min_market(self.settings.CRYPTO_SYMBOL)
        if market is None:
            logger.warning("No active 5-min market found")
            return
        logger.info(f"Market found: {market['question'][:60]} | Up={market['up_price']:.2f} Down={market['down_price']:.2f}")
        # 7. Place trade — outcomes are "Up" / "Down"
        side = "Up" if signal == 1 else "Down"
        entry_price = market["up_price"] if side == "Up" else market["down_price"]
        token_id = market["token_up"] if side == "Up" else market["token_down"]
        btc_price = enriched["close"].iloc[-1]
        status = "dry_run_open" if self.dry_run else "open"
        if not self.dry_run:
            self._place_order(market["market_id"], token_id, side, size, entry_price)
        self.db.save_crypto_trade(
            strategy=self.strategy_name, symbol=self.settings.CRYPTO_SYMBOL,
            market_id=market["market_id"], side=side,
            entry_price=entry_price, strike_price=None,
            btc_price_at_entry=btc_price, amount=size,
            status=status, signal_data=json.dumps(meta),
            token_id=token_id,
        )
        logger.info(
            f"{'DRY RUN' if self.dry_run else 'LIVE'}: {side} ${size:.2f} @ {entry_price:.2f} | "
            f"{market['question'][:60]}"
        )

    def _place_order(self, market_id, token_id, side, size, price):
        if self._clob_client is None:
            from py_clob_client.client import ClobClient
            self._clob_client = ClobClient(
                self.settings.POLYMARKET_CLOB_URL,
                key=self.settings.POLYMARKET_PRIVATE_KEY,
                chain_id=137,
                funder=self.settings.POLYMARKET_FUNDER_ADDRESS or None,
            )
        from py_clob_client.order_builder.constants import BUY
        self._clob_client.create_and_post_order({
            "token_id": token_id, "price": round(price, 2),
            "size": round(size / price, 2), "side": BUY,
        })

    async def _settle_open_trades(self):
        trades = self.db.get_open_crypto_trades()
        for trade in trades:
            if not trade.get("market_id"):
                continue
            token_id = trade.get("token_id")
            resolution = await self.scanner.check_resolution(trade["market_id"], token_id=token_id)
            if resolution is None:
                continue
            won = (trade["side"] == resolution)
            pnl = calc_crypto_pnl(trade["entry_price"], trade["amount"], won, self.settings.POLYMARKET_FEE)
            if trade["status"] == "dry_run_open":
                status = "dry_run_won" if won else "dry_run_lost"
            else:
                status = "won" if won else "lost"
            self.db.settle_crypto_trade(trade["id"], status=status, pnl=pnl, expected_status=trade["status"])
            self.tracker.update_after_trade(trade["strategy"], won=won, pnl=pnl)
            logger.info(f"Settled: {trade['strategy']} {trade['side']} -> {resolution} P&L: ${pnl:.2f}")
