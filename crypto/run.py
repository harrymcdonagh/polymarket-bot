import asyncio
import sys
import logging
from src.config import Settings


def main():
    settings = Settings()

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("crypto-bot")

    # Mutual exclusion
    modes = {"--bot", "--settle", "--backtest"}
    active = modes & set(sys.argv)
    if len(active) > 1:
        logger.error(f"Cannot combine modes: {', '.join(active)}")
        sys.exit(1)
    if not active:
        active = {"--bot"}  # default

    if "--backtest" in active:
        from src.db import Database
        from src.backtester.runner import BacktestRunner
        from src.data_feed import CryptoDataFeed

        logger.info("=== BACKTEST MODE ===")
        db = Database(settings.DB_PATH)
        db.init()

        async def run_backtest():
            feed = CryptoDataFeed()
            symbol = f"{settings.CRYPTO_SYMBOL}/USDT"
            logger.info(f"Fetching {settings.CRYPTO_CANDLE_WINDOW} candles for {symbol}...")
            df = await feed.fetch_candles(symbol, limit=settings.CRYPTO_CANDLE_WINDOW, min_candles=60)
            await feed.close()
            if df is None:
                logger.error("Failed to fetch candle data")
                return
            runner = BacktestRunner(db=db, fee_pct=settings.POLYMARKET_FEE)
            results = runner.run_grid(df, symbol=settings.CRYPTO_SYMBOL)
            logger.info(f"\n=== BACKTEST RESULTS ({len(results)} configs) ===")
            for r in results[:10]:
                logger.info(
                    f"{r['strategy']:12s} {str(r['params']):50s} "
                    f"trades={r['total_trades']:3d} win={r['win_rate']:.1%} "
                    f"exp={r['expectancy']:.4f} pnl={r['total_pnl']:.2f}"
                )

        asyncio.run(run_backtest())
        return

    if "--settle" in active:
        from src.settler import CryptoSettler
        logger.info("=== CRYPTO SETTLER MODE ===")
        settler = CryptoSettler(settings)
        asyncio.run(settler.run_loop(interval=300))
        return

    # --bot mode (default)
    from src.bot import CryptoBot
    dry_run = "--live" not in sys.argv
    if dry_run:
        logger.info("=== CRYPTO BOT: DRY RUN ===")
    else:
        logger.warning("=== CRYPTO BOT: LIVE MODE ===")
        if not settings.POLYMARKET_PRIVATE_KEY:
            logger.error("POLYMARKET_PRIVATE_KEY not set")
            sys.exit(1)

    bot = CryptoBot(settings=settings, dry_run=dry_run)
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
