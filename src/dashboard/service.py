import asyncio
import collections
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.db import Database
from src.pipeline import Pipeline
from src.dashboard.log_handler import DashboardLogHandler, read_shared_logs
from src.activity import read_activity

try:
    from src.predictor.trainer import train_from_history
except ImportError:
    train_from_history = None  # type: ignore

logger = logging.getLogger(__name__)

UPDATABLE_SETTINGS = {
    "BANKROLL", "MAX_BET_FRACTION", "CONFIDENCE_THRESHOLD",
    "MIN_EDGE_THRESHOLD", "MAX_DAILY_LOSS", "LOOP_INTERVAL", "SETTLEMENT_INTERVAL",
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
        self._settlement_task: asyncio.Task | None = None
        self._log_buffer: collections.deque = collections.deque(maxlen=200)
        self._last_error: str | None = None
        self._last_scan_results = []
        self._current_activity = {"stage": "idle", "detail": ""}
        self._dry_run_trades: list[dict] = []

        # Install log handler
        self._log_handler = DashboardLogHandler(self._log_buffer)
        logging.getLogger().addHandler(self._log_handler)

        # Init pipeline (may fail gracefully)
        try:
            self.pipeline = Pipeline(
                settings=self.settings, db_path=db_path,
                status_callback=self._on_activity,
            )
        except Exception as e:
            logger.warning(f"Pipeline init failed: {e}")
            self.pipeline = None

    # --- Read methods ---

    def get_stats(self) -> dict:
        trade_stats = self.db.get_trade_stats()
        pred_stats = self.db.get_prediction_stats()
        accuracy = self.db.get_prediction_accuracy()
        # Calculate total unrealised PnL from open positions
        from src.pnl import calc_unrealised_pnl
        open_pos = self.db.get_open_positions_with_prices()
        unrealised = sum(
            calc_unrealised_pnl(
                side=t["side"], amount=t["amount"],
                entry_price=t["price"], current_yes_price=t["current_price"],
            )
            for t in open_pos if t.get("current_price") is not None
        )
        return {
            **trade_stats,
            **pred_stats,
            "prediction_accuracy": accuracy,
            "open_trades": len(self.db.get_open_trades()),
            "today_pnl": self.db.get_daily_pnl(),
            "snapshot_count": self.db.get_snapshot_count(),
            "unrealised_pnl": round(unrealised, 2),
        }

    def get_recent_trades(self, limit: int = 20) -> list[dict]:
        real_trades = self.db.get_recent_trades_with_names(limit)
        combined = self._dry_run_trades + real_trades
        combined.sort(key=lambda t: t.get("executed_at", ""), reverse=True)
        return combined[:limit]

    def get_flagged_markets(self) -> list:
        if self._last_scan_results:
            return self._last_scan_results
        # Fall back to recent flagged snapshots joined with prediction outcomes
        return self.db.get_flagged_markets_with_predictions(limit=30)

    def get_pnl_history(self) -> list[dict]:
        snapshots = self.db.get_pnl_snapshots()
        if not snapshots:
            return []
        return [
            {
                "date": s["snapshot_at"][:16].replace("T", " "),
                "cumulative_pnl": s["settled_pnl"],
                "unrealised_pnl": s["unrealised_pnl"],
                "total_pnl": s["total_pnl"],
                "win_rate": s.get("win_rate"),
                "brier_score": s.get("brier_score"),
            }
            for s in snapshots
        ]

    def get_open_positions(self) -> list[dict]:
        from src.pnl import calc_unrealised_pnl
        positions = self.db.get_open_positions_with_prices()
        result = []
        for p in positions:
            current_price = p.get("current_price")
            pnl = None
            if current_price is not None:
                pnl = calc_unrealised_pnl(
                    side=p["side"],
                    amount=p["amount"],
                    entry_price=p["price"],
                    current_yes_price=current_price,
                )
            result.append({
                "trade_id": p["id"],
                "market_id": p["market_id"],
                "question": p.get("question") or p["market_id"],
                "side": p["side"],
                "amount": p["amount"],
                "entry_price": p["price"],
                "current_price": current_price,
                "unrealised_pnl": round(pnl, 2) if pnl is not None else None,
                "price_updated_at": p.get("price_updated_at"),
            })
        return result

    def get_lessons(self, category: str | None = None) -> list[dict]:
        return self.db.get_lessons(category)

    def get_feature_suggestions(self) -> list[dict]:
        rules = self.db.get_latest_rules()
        if not rules or not rules.get("feature_suggestions"):
            return []
        import json
        try:
            return json.loads(rules["feature_suggestions"])
        except (json.JSONDecodeError, TypeError):
            return []

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

    def _on_activity(self, stage: str, detail: str = ""):
        self._current_activity = {"stage": stage, "detail": detail}

    def get_activity(self) -> dict:
        # Try reading from shared file first (for cross-process status)
        file_activity = read_activity()
        if file_activity.get("updated_at"):
            return file_activity
        return self._current_activity

    def get_recent_logs(self, limit: int = 50) -> list[str]:
        # Read from shared log file (written by bot/settler processes)
        shared = read_shared_logs(limit)
        # Merge with any local in-memory logs from this process
        local = list(self._log_buffer)
        combined = shared + local
        # Deduplicate while preserving order
        seen = set()
        result = []
        for line in combined:
            if line not in seen:
                seen.add(line)
                result.append(line)
        return result[-limit:]

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
                self._last_scan_results = self.pipeline.last_flagged_markets
                self._dry_run_trades = self.pipeline.dry_run_trades.copy()
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
        "SETTLEMENT_INTERVAL": lambda v: v >= 30 or "SETTLEMENT_INTERVAL must be >= 30",
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
            if self._settlement_task and not self._settlement_task.done():
                self._settlement_task.cancel()
            self._loop_task = None
            self._settlement_task = None
            return {"loop": False}
        interval = interval or self.settings.LOOP_INTERVAL
        self._loop_task = asyncio.create_task(self._loop(interval))
        self._settlement_task = asyncio.create_task(
            self._settlement_loop(self.settings.SETTLEMENT_INTERVAL)
        )
        return {"loop": True, "interval": interval}

    async def _loop(self, interval: int):
        while True:
            try:
                if self.pipeline:
                    async with self._scan_lock:
                        await self.pipeline.run_cycle(dry_run=self.dry_run)
                        self._last_scan_results = self.pipeline.last_flagged_markets
                        self._dry_run_trades = self.pipeline.dry_run_trades.copy()
                        self._cycle_count += 1
                        self._last_error = None
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"Loop cycle failed: {e}")
                await asyncio.sleep(interval)

    async def _settlement_loop(self, interval: int):
        from src.settler.settler import Settler
        if not self.pipeline:
            return
        settler = Settler(
            db=self.pipeline.db, notifier=self.pipeline.notifier,
            postmortem=self.pipeline.postmortem,
            gamma_url=self.pipeline.settings.POLYMARKET_GAMMA_URL,
            settings=self.pipeline.settings,
        )
        await asyncio.sleep(60)  # let first pipeline cycle run first
        while True:
            try:
                logger.info("=== SETTLEMENT CHECK ===")
                await settler.run()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Settlement check failed: {e}")
            await asyncio.sleep(interval)

    async def shutdown(self):
        """Graceful shutdown: cancel loop, wait for scan, cancel settlements, close DB."""
        for task in [self._loop_task, self._settlement_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5)
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
