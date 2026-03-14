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
        fastapi_app = create_app(settings=settings)
        fastapi_app.state.service.dry_run = "--live" not in sys.argv
        logger.info("Starting web dashboard on http://127.0.0.1:8050")
        uvicorn.run(fastapi_app, host="127.0.0.1", port=8050, log_level=settings.LOG_LEVEL.lower())
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
    pipeline = Pipeline(settings=settings)

    if "--loop" in sys.argv:
        interval = settings.LOOP_INTERVAL
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])
        logger.info(f"=== LOOP MODE: running every {interval}s ===")
        asyncio.run(_loop(pipeline, dry_run, interval))
    else:
        asyncio.run(pipeline.run_cycle(dry_run=dry_run))


async def _loop(pipeline, dry_run: bool, interval: int):
    logger = logging.getLogger("polymarket-bot")
    while True:
        try:
            await pipeline.run_cycle(dry_run=dry_run)
        except Exception as e:
            logger.error(f"Cycle failed: {e}")
        logger.info(f"Sleeping {interval}s until next cycle...")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    main()
