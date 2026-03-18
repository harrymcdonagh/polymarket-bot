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
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])
        logger.info(f"=== LOOP MODE: pipeline every {interval}s (settlement handled by standalone service) ===")
        asyncio.run(_loop(pipeline, dry_run, interval))
    else:
        asyncio.run(pipeline.run_cycle(dry_run=dry_run))


async def _loop(pipeline, dry_run: bool, interval: int):
    logger = logging.getLogger("polymarket-bot")
    if pipeline.notifier.is_enabled:
        await pipeline.notifier.send(pipeline.notifier.format_startup())

    from datetime import datetime, timezone, timedelta
    import json, os
    bot_activity_path = "data/bot_activity.json"

    def _write_bot_next(next_at: str | None = None):
        try:
            data = {"next_at": next_at, "interval": interval, "updated_at": datetime.now(timezone.utc).isoformat()}
            os.makedirs(os.path.dirname(bot_activity_path) or ".", exist_ok=True)
            with open(bot_activity_path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    while True:
        try:
            await pipeline.run_cycle(dry_run=dry_run)
        except Exception as e:
            logger.error(f"Cycle failed: {e}")
        next_at = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat()
        _write_bot_next(next_at)
        logger.info(f"Sleeping {interval}s until next pipeline cycle...")
        await asyncio.sleep(interval)


async def _settle_loop(settler, interval: int):
    logger = logging.getLogger("polymarket-bot")
    from datetime import datetime, timezone, timedelta
    import json, os
    path = "data/settler_activity.json"

    def _write_settler_activity(stage: str, detail: str = "", next_at: str | None = None):
        try:
            data = {
                "stage": stage, "detail": detail,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "interval": interval,
            }
            if next_at:
                data["next_at"] = next_at
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    while True:
        _write_settler_activity("settling", "Checking markets")
        try:
            await settler.run()
        except Exception as e:
            logger.error(f"Settlement cycle failed: {e}")
        next_at = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat()
        _write_settler_activity("idle", "", next_at)
        logger.info(f"Sleeping {interval}s until next settlement check...")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    main()
