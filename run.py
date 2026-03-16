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
    logger = logging.getLogger("polymarket-bot")

    # Ensure data directory exists
    import os
    os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)

    if "--train" in sys.argv:
        from src.predictor.trainer import train_from_history
        logger.info("Training XGBoost model on historical data...")
        asyncio.run(train_from_history())
        return

    if "--dashboard" in sys.argv:
        from src.dashboard.service import DashboardService
        from src.dashboard.terminal import DashboardApp
        svc = DashboardService(settings=settings)
        svc.dry_run = "--live" not in sys.argv
        app = DashboardApp(svc)
        if "--loop" in sys.argv:
            app.call_later(lambda: asyncio.ensure_future(svc.toggle_loop()))
        app.run()
        return

    if "--web" in sys.argv:
        from src.dashboard.web import create_app
        import uvicorn
        import os

        os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)

        host = "127.0.0.1"
        for arg in sys.argv:
            if arg.startswith("--host="):
                host = arg.split("=")[1]

        fastapi_app = create_app(settings=settings)
        fastapi_app.state.service.dry_run = "--live" not in sys.argv
        logger.info(f"Starting web dashboard on http://{host}:8050")
        uvicorn.run(fastapi_app, host=host, port=8050, log_level=settings.LOG_LEVEL.lower())
        return

    if "--settle" in sys.argv:
        from src.settler.settler import Settler
        from src.notifications.telegram import TelegramNotifier
        from src.db import Database
        from src.postmortem.postmortem import PostmortemAnalyzer
        import os

        os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)
        db = Database(settings.DB_PATH)
        db.init()
        notifier = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
        postmortem = PostmortemAnalyzer(settings=settings, db=db)
        settler = Settler(db=db, notifier=notifier, postmortem=postmortem,
                          gamma_url=settings.POLYMARKET_GAMMA_URL)

        from src.dashboard.log_handler import SharedFileLogHandler
        logging.getLogger().addHandler(SharedFileLogHandler())

        interval = 3600
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])

        logger.info(f"=== SETTLEMENT MONITOR: checking every {interval}s ===")
        asyncio.run(_settle_loop(settler, interval))
        return

    dry_run = "--live" not in sys.argv

    if dry_run:
        logger.info("=== DRY RUN MODE (pass --live to execute real trades) ===")
    else:
        logger.warning("=== LIVE MODE - REAL TRADES WILL BE PLACED ===")
        if not settings.POLYMARKET_PRIVATE_KEY:
            logger.error("POLYMARKET_PRIVATE_KEY not set. Cannot trade in live mode.")
            sys.exit(1)

    from src.pipeline import Pipeline
    from src.dashboard.log_handler import SharedFileLogHandler
    logging.getLogger().addHandler(SharedFileLogHandler())
    pipeline = Pipeline(settings=settings)

    if "--loop" in sys.argv:
        interval = settings.LOOP_INTERVAL
        settle_interval = settings.SETTLEMENT_INTERVAL
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])
            if arg.startswith("--settle-interval="):
                settle_interval = int(arg.split("=")[1])
        logger.info(f"=== LOOP MODE: pipeline every {interval}s, settlement every {settle_interval}s ===")
        asyncio.run(_loop(pipeline, dry_run, interval, settle_interval))
    else:
        asyncio.run(pipeline.run_cycle(dry_run=dry_run))


async def _loop(pipeline, dry_run: bool, interval: int, settle_interval: int = 1800):
    logger = logging.getLogger("polymarket-bot")
    if pipeline.notifier.is_enabled:
        await pipeline.notifier.send(pipeline.notifier.format_startup())

    from src.settler.settler import Settler
    settler = Settler(
        db=pipeline.db, notifier=pipeline.notifier,
        postmortem=pipeline.postmortem,
        gamma_url=pipeline.settings.POLYMARKET_GAMMA_URL,
    )

    async def _pipeline_loop():
        while True:
            try:
                await pipeline.run_cycle(dry_run=dry_run)
            except Exception as e:
                logger.error(f"Cycle failed: {e}")
            logger.info(f"Sleeping {interval}s until next pipeline cycle...")
            await asyncio.sleep(interval)

    async def _settlement_loop():
        # Wait a bit so the first pipeline cycle runs first
        await asyncio.sleep(60)
        while True:
            try:
                logger.info("=== SETTLEMENT CHECK ===")
                await settler.run()
            except Exception as e:
                logger.error(f"Settlement check failed: {e}")
            logger.info(f"Sleeping {settle_interval}s until next settlement check...")
            await asyncio.sleep(settle_interval)

    await asyncio.gather(_pipeline_loop(), _settlement_loop())


async def _settle_loop(settler, interval: int):
    logger = logging.getLogger("polymarket-bot")
    while True:
        try:
            await settler.run()
        except Exception as e:
            logger.error(f"Settlement cycle failed: {e}")
        logger.info(f"Sleeping {interval}s until next settlement check...")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    main()
