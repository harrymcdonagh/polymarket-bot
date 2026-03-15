import asyncio
import collections
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.db import Database
from src.pipeline import Pipeline
from src.dashboard.log_handler import DashboardLogHandler

try:
    from src.predictor.trainer import train_from_history
except ImportError:
    train_from_history = None  # type: ignore

logger = logging.getLogger(__name__)

UPDATABLE_SETTINGS = {
    "BANKROLL", "MAX_BET_FRACTION", "CONFIDENCE_THRESHOLD",
    "MIN_EDGE_THRESHOLD", "MAX_DAILY_LOSS", "LOOP_INTERVAL",
    "SOURCE_WEIGHT_NEWSAPI", "SOURCE_WEIGHT_RSS_MAJOR",
    "SOURCE_WEIGHT_RSS_PREDICTION", "SOURCE_WEIGHT_RSS_GOOGLE",
    "SOURCE_WEIGHT_TWITTER", "SOURCE_WEIGHT_REDDIT",
    "RESEARCH_TIMEOUT",
}


class DashboardService:
    def __init__(self, settings: Settings | None = None, db_path: str = "bot.db"):
        self.settings = settings or Settings()
        self.db = Database(db_path)
        self.db.init()
        self.dry_run = True
        self._cycle_count = 0
        self._started_at = datetime.now(timezone.utc)
        self._scan_lock = asyncio.Lock()
        self._loop_task: asyncio.Task | None = None
        self._log_buffer: collections.deque = collections.deque(maxlen=200)
        self._last_error: str | None = None
        self._last_scan_results = []

        # Install log handler
        self._log_handler = DashboardLogHandler(self._log_buffer)
        logging.getLogger().addHandler(self._log_handler)

        # Init pipeline (may fail gracefully)
        try:
            self.pipeline = Pipeline(settings=self.settings, db_path=db_path)
        except Exception as e:
            logger.warning(f"Pipeline init failed: {e}")
            self.pipeline = None

    # --- Read methods ---

    def get_stats(self) -> dict:
        trade_stats = self.db.get_trade_stats()
        return {
            **trade_stats,
            "open_trades": len(self.db.get_open_trades()),
            "today_pnl": self.db.get_daily_pnl(),
            "snapshot_count": self.db.get_snapshot_count(),
        }

    def get_recent_trades(self, limit: int = 20) -> list[dict]:
        return self.db.get_recent_trades_with_names(limit)

    def get_flagged_markets(self) -> list:
        return self._last_scan_results

    def get_pnl_history(self) -> list[dict]:
        return self.db.get_pnl_history()

    def get_lessons(self, category: str | None = None) -> list[dict]:
        return self.db.get_lessons(category)

    def get_bot_status(self) -> dict:
        uptime = (datetime.now(timezone.utc) - self._started_at).total_seconds()
        return {
            "pipeline_ready": self.pipeline is not None,
            "dry_run": self.dry_run,
            "loop_active": self._loop_task is not None and not self._loop_task.done(),
            "scanning": self._scan_lock.locked(),
            "cycle_count": self._cycle_count,
            "uptime_seconds": int(uptime),
            "last_error": self._last_error,
        }

    def get_recent_logs(self, limit: int = 50) -> list[str]:
        logs = list(self._log_buffer)
        return logs[-limit:]

    # --- Control methods ---

    async def trigger_scan(self, dry_run: bool = True) -> dict:
        if self._scan_lock.locked():
            return {"status": "already_running"}
        if self.pipeline is None:
            return {"status": "error", "error": "Pipeline not initialized"}
        asyncio.create_task(self._run_scan(dry_run))
        return {"status": "started"}

    async def _run_scan(self, dry_run: bool):
        async with self._scan_lock:
            try:
                await self.pipeline.run_cycle(dry_run=dry_run)
                self._cycle_count += 1
                self._last_error = None
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"Scan cycle failed: {e}")

    async def trigger_retrain(self) -> dict:
        if self._scan_lock.locked():
            return {"status": "already_running"}
        asyncio.create_task(self._run_retrain())
        return {"status": "started"}

    async def _run_retrain(self):
        async with self._scan_lock:
            try:
                model = await train_from_history()
                if self.pipeline:
                    self.pipeline.xgb_model = model
                    logger.info("Model retrained and loaded into pipeline")
                self._last_error = None
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"Retrain failed: {e}")

    _SETTING_VALIDATORS = {
        "BANKROLL": lambda v: v > 0 or "BANKROLL must be > 0",
        "MAX_BET_FRACTION": lambda v: 0 < v <= 1 or "MAX_BET_FRACTION must be 0 < x <= 1",
        "CONFIDENCE_THRESHOLD": lambda v: 0 <= v <= 1 or "CONFIDENCE_THRESHOLD must be 0 <= x <= 1",
        "MIN_EDGE_THRESHOLD": lambda v: v >= 0 or "MIN_EDGE_THRESHOLD must be >= 0",
        "MAX_DAILY_LOSS": lambda v: v > 0 or "MAX_DAILY_LOSS must be > 0",
        "LOOP_INTERVAL": lambda v: v >= 30 or "LOOP_INTERVAL must be >= 30",
        "SOURCE_WEIGHT_NEWSAPI": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
        "SOURCE_WEIGHT_RSS_MAJOR": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
        "SOURCE_WEIGHT_RSS_PREDICTION": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
        "SOURCE_WEIGHT_RSS_GOOGLE": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
        "SOURCE_WEIGHT_TWITTER": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
        "SOURCE_WEIGHT_REDDIT": lambda v: 0 < v <= 1 or "Weight must be 0 < x <= 1",
        "RESEARCH_TIMEOUT": lambda v: v >= 1 or "RESEARCH_TIMEOUT must be >= 1",
    }

    def update_settings(self, key: str, value) -> dict:
        if key not in UPDATABLE_SETTINGS:
            return {"ok": False, "error": f"Cannot update '{key}' at runtime"}
        # Validate before applying
        validator = self._SETTING_VALIDATORS.get(key)
        if validator:
            try:
                result = validator(float(value))
                if result is not True:
                    return {"ok": False, "error": str(result)}
            except (TypeError, ValueError) as e:
                return {"ok": False, "error": str(e)}
        old_value = getattr(self.settings, key)
        try:
            setattr(self.settings, key, value)
            return {"ok": True, "key": key, "value": getattr(self.settings, key)}
        except Exception as e:
            setattr(self.settings, key, old_value)
            return {"ok": False, "error": str(e)}

    async def toggle_loop(self, interval: int | None = None) -> dict:
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            self._loop_task = None
            return {"loop": False}
        interval = interval or self.settings.LOOP_INTERVAL
        self._loop_task = asyncio.create_task(self._loop(interval))
        return {"loop": True, "interval": interval}

    async def _loop(self, interval: int):
        while True:
            try:
                if self.pipeline:
                    async with self._scan_lock:
                        await self.pipeline.run_cycle(dry_run=self.dry_run)
                        self._cycle_count += 1
                        self._last_error = None
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"Loop cycle failed: {e}")
                await asyncio.sleep(interval)

    async def shutdown(self):
        """Graceful shutdown: cancel loop, wait for scan, cancel settlements, close DB."""
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await asyncio.wait_for(self._loop_task, timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if self._scan_lock.locked():
            try:
                await asyncio.wait_for(self._scan_lock.acquire(), timeout=30)
                self._scan_lock.release()
            except asyncio.TimeoutError:
                logger.warning("Shutdown: scan still running after 30s")
        if self.pipeline and hasattr(self.pipeline, '_settlement_tasks'):
            for task in self.pipeline._settlement_tasks:
                if not task.done():
                    task.cancel()
        self.db.close()
        logging.getLogger().removeHandler(self._log_handler)
