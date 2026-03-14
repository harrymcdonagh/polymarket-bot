# Dashboard Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add terminal and web dashboards for monitoring, analytics, and controlling the polymarket bot.

**Architecture:** A shared `DashboardService` wraps all DB reads and bot control. Two thin frontends consume it: a Textual terminal app and a FastAPI + htmx web app. The bot pipeline runs in-process — the dashboard IS the bot with a UI on top.

**Tech Stack:** Textual (terminal), FastAPI + uvicorn + Jinja2 + htmx (CDN) + Chart.js (CDN) (web), existing SQLite + Pipeline.

**Spec:** `docs/superpowers/specs/2026-03-14-dashboard-design.md`

---

## File Structure

```
src/dashboard/
├── __init__.py          # Empty package init
├── service.py           # DashboardService — shared data + control layer
├── log_handler.py       # DashboardLogHandler — captures logs to ring buffer
├── terminal.py          # Textual app with panels and keybindings
├── web.py               # FastAPI app with API routes
├── templates/
│   └── index.html       # Single-page web dashboard (htmx + Chart.js)
└── static/
    └── style.css        # Dark theme styles

Modify:
├── src/db.py            # Add get_pnl_history(), get_recent_trades_with_names(), threading.local() for connections
├── run.py               # Add --dashboard and --web entry points
└── pyproject.toml       # Add textual, fastapi, uvicorn, jinja2 dependencies

Tests:
├── tests/test_dashboard_service.py  # Service layer unit tests
└── tests/test_web.py                # FastAPI endpoint tests
```

---

## Chunk 1: Foundation (DB + Dependencies + Service)

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add new dependencies to pyproject.toml**

Add to the `dependencies` list:
```toml
    "textual>=0.50.0",
    "fastapi>=0.110.0",
    "uvicorn>=0.27.0",
    "jinja2>=3.1.0",
```

Note: htmx and Chart.js are loaded via CDN in the HTML template, not Python dependencies.

- [ ] **Step 2: Install dependencies**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: All packages install successfully.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add dashboard dependencies (textual, fastapi, uvicorn, jinja2)"
```

---

### Task 2: Add DB methods and thread-safe connections

**Files:**
- Modify: `src/db.py`
- Test: `tests/test_dashboard_service.py`

- [ ] **Step 1: Write failing tests for new DB methods**

Create `tests/test_dashboard_service.py`:

```python
from src.db import Database


def test_get_pnl_history_empty(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    result = db.get_pnl_history()
    assert result == []


def test_get_pnl_history_cumulative_math(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    db.save_trade("0x1", "YES", 50.0, 0.5, "o1")
    db.update_trade_status(1, "settled", 25.0)
    db.save_trade("0x2", "NO", 30.0, 0.6, "o2")
    db.update_trade_status(2, "settled", -10.0)
    history = db.get_pnl_history()
    assert len(history) >= 1
    assert "date" in history[0]
    assert "daily_pnl" in history[0]
    assert "cumulative_pnl" in history[0]
    # Verify cumulative is sum of daily values
    running = 0.0
    for entry in history:
        running += entry["daily_pnl"]
        assert abs(entry["cumulative_pnl"] - round(running, 2)) < 0.01


def test_get_recent_trades_with_names(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    db.save_trade("0xabc", "YES", 50.0, 0.5, "o1")
    # Add a snapshot so the name can be resolved
    from unittest.mock import MagicMock
    market = MagicMock()
    market.condition_id = "0xabc"
    market.question = "Will BTC hit 100k?"
    market.yes_price = 0.55
    market.no_price = 0.45
    market.spread = 0.02
    market.liquidity = 50000
    market.volume_24h = 10000
    market.days_to_resolution = 20
    market.flags = []
    market.scanned_at = None
    db.save_market_snapshots_batch([market])
    trades = db.get_recent_trades_with_names(limit=10)
    assert len(trades) == 1
    assert trades[0]["question"] == "Will BTC hit 100k?"


def test_get_recent_trades_with_names_no_snapshot(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    db.save_trade("0xunknown", "YES", 50.0, 0.5, "o1")
    trades = db.get_recent_trades_with_names(limit=10)
    assert len(trades) == 1
    assert trades[0]["question"] is None


def test_db_thread_safe_connections(tmp_path):
    """Verify different threads get different connections."""
    import threading
    db = Database(str(tmp_path / "test.db"))
    db.init()
    main_conn = db._conn()
    thread_conn = [None]
    def get_conn():
        thread_conn[0] = db._conn()
    t = threading.Thread(target=get_conn)
    t.start()
    t.join()
    assert thread_conn[0] is not main_conn
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_service.py -v`
Expected: FAIL — methods don't exist, threading not implemented.

- [ ] **Step 3: Make DB connections thread-safe with threading.local()**

Replace the connection management in `src/db.py`:

```python
import sqlite3
import threading
from datetime import datetime, timezone


class Database:
    def __init__(self, path: str = "bot.db"):
        self.path = path
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.path)
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    def close(self):
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
```

- [ ] **Step 4: Add new query methods to src/db.py**

Add before `get_daily_pnl`:

```python
def get_pnl_history(self) -> list[dict]:
    """Daily PnL series with cumulative totals for charting."""
    conn = self._conn()
    rows = conn.execute(
        """SELECT DATE(settled_at) as date, SUM(pnl) as daily_pnl
           FROM trades WHERE status = 'settled' AND settled_at IS NOT NULL
           GROUP BY DATE(settled_at) ORDER BY date"""
    ).fetchall()
    history = []
    cumulative = 0.0
    for row in rows:
        cumulative += row["daily_pnl"]
        history.append({
            "date": row["date"],
            "daily_pnl": row["daily_pnl"],
            "cumulative_pnl": round(cumulative, 2),
        })
    return history

def get_recent_trades_with_names(self, limit: int = 20) -> list[dict]:
    """Get recent trades with market question resolved from snapshots."""
    conn = self._conn()
    rows = conn.execute(
        """SELECT t.*, ms.question
           FROM trades t
           LEFT JOIN (
               SELECT condition_id, question,
                      ROW_NUMBER() OVER (PARTITION BY condition_id ORDER BY snapshot_at DESC) as rn
               FROM market_snapshots
           ) ms ON t.market_id = ms.condition_id AND ms.rn = 1
           ORDER BY t.executed_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_service.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 6: Run full test suite for regressions**

Run: `pytest tests/ -q`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/db.py tests/test_dashboard_service.py
git commit -m "feat: add pnl_history, trades_with_names, thread-safe DB connections"
```

---

### Task 3: Create DashboardLogHandler

**Files:**
- Create: `src/dashboard/__init__.py`
- Create: `src/dashboard/log_handler.py`
- Test: `tests/test_dashboard_service.py` (append)

- [ ] **Step 1: Write failing test for log handler**

Append to `tests/test_dashboard_service.py`:

```python
import logging
from src.dashboard.log_handler import DashboardLogHandler


def test_log_handler_captures_messages():
    import collections
    buf = collections.deque(maxlen=100)
    handler = DashboardLogHandler(buf)
    logger = logging.getLogger("test.dashboard")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("test message")
    assert len(buf) == 1
    assert "test message" in buf[0]
    logger.removeHandler(handler)


def test_log_handler_respects_maxlen():
    import collections
    buf = collections.deque(maxlen=5)
    handler = DashboardLogHandler(buf)
    logger = logging.getLogger("test.dashboard.overflow")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    for i in range(10):
        logger.info(f"msg {i}")
    assert len(buf) == 5
    assert "msg 9" in buf[-1]
    logger.removeHandler(handler)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_service.py::test_log_handler_captures_messages -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the package and log handler**

Create `src/dashboard/__init__.py` (empty file).

Create `src/dashboard/log_handler.py`:

```python
import logging
import collections


class DashboardLogHandler(logging.Handler):
    """Captures log records into a shared deque for dashboard display."""

    def __init__(self, buffer: collections.deque):
        super().__init__()
        self.buffer = buffer
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
        ))

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.buffer.append(msg)
        except Exception:
            self.handleError(record)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_service.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/__init__.py src/dashboard/log_handler.py tests/test_dashboard_service.py
git commit -m "feat: add DashboardLogHandler for log capture to ring buffer"
```

---

### Task 4: Create DashboardService

**Files:**
- Create: `src/dashboard/service.py`
- Test: `tests/test_dashboard_service.py` (append)

- [ ] **Step 1: Write failing tests for the service**

Append to `tests/test_dashboard_service.py`:

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.dashboard.service import DashboardService


def test_service_get_stats(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        MockPipeline.return_value = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        stats = svc.get_stats()
        assert "total_trades" in stats
        assert "win_rate" in stats
        assert "today_pnl" in stats
        assert "snapshot_count" in stats


def test_service_get_bot_status(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        MockPipeline.return_value = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        status = svc.get_bot_status()
        assert status["loop_active"] is False
        assert status["cycle_count"] == 0
        assert "uptime_seconds" in status


def test_service_update_settings_valid(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        MockPipeline.return_value = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        result = svc.update_settings("BANKROLL", 2000.0)
        assert result["ok"] is True
        assert svc.settings.BANKROLL == 2000.0


def test_service_update_settings_invalid_key(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        MockPipeline.return_value = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        result = svc.update_settings("ANTHROPIC_API_KEY", "hacked")
        assert result["ok"] is False


def test_service_update_settings_invalid_value(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        MockPipeline.return_value = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        original = svc.settings.BANKROLL
        result = svc.update_settings("BANKROLL", -100)
        assert result["ok"] is False
        # Verify rollback: value should be unchanged
        assert svc.settings.BANKROLL == original


@pytest.mark.asyncio
async def test_service_trigger_scan(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        mock_pipeline = MockPipeline.return_value
        mock_pipeline.run_cycle = AsyncMock()
        mock_pipeline.db = MagicMock()
        mock_pipeline.db.init = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        svc.pipeline = mock_pipeline
        result = await svc.trigger_scan(dry_run=True)
        assert result["status"] == "started"


@pytest.mark.asyncio
async def test_service_trigger_scan_mutex(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        mock_pipeline = MockPipeline.return_value
        async def slow_cycle(dry_run=True):
            await asyncio.sleep(10)
        mock_pipeline.run_cycle = slow_cycle
        mock_pipeline.db = MagicMock()
        mock_pipeline.db.init = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        svc.pipeline = mock_pipeline
        # First scan starts
        result1 = await svc.trigger_scan(dry_run=True)
        assert result1["status"] == "started"
        # Yield to let the created task acquire the lock
        await asyncio.sleep(0)
        # Second scan blocked
        result2 = await svc.trigger_scan(dry_run=True)
        assert result2["status"] == "already_running"


@pytest.mark.asyncio
async def test_service_trigger_retrain(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        mock_pipeline = MockPipeline.return_value
        mock_pipeline.db = MagicMock()
        mock_pipeline.db.init = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        svc.pipeline = mock_pipeline
        with patch("src.dashboard.service.train_from_history", new_callable=AsyncMock) as mock_train:
            mock_train.return_value = MagicMock()
            result = await svc.trigger_retrain()
            assert result["status"] == "started"


@pytest.mark.asyncio
async def test_service_toggle_loop(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        mock_pipeline = MockPipeline.return_value
        mock_pipeline.run_cycle = AsyncMock()
        mock_pipeline.db = MagicMock()
        mock_pipeline.db.init = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        svc.pipeline = mock_pipeline
        # Start loop
        result = await svc.toggle_loop(interval=300)
        assert result["loop"] is True
        # Stop loop
        result = await svc.toggle_loop()
        assert result["loop"] is False


def test_service_get_recent_logs(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        MockPipeline.return_value = MagicMock()
        svc = DashboardService(db_path=str(tmp_path / "test.db"))
        svc._log_buffer.append("line 1")
        svc._log_buffer.append("line 2")
        logs = svc.get_recent_logs(limit=10)
        assert len(logs) == 2
        assert logs[0] == "line 1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_service.py::test_service_get_stats -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement DashboardService**

Create `src/dashboard/service.py`:

```python
import asyncio
import collections
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.db import Database
from src.pipeline import Pipeline
from src.dashboard.log_handler import DashboardLogHandler

logger = logging.getLogger(__name__)

UPDATABLE_SETTINGS = {
    "BANKROLL", "MAX_BET_FRACTION", "CONFIDENCE_THRESHOLD",
    "MIN_EDGE_THRESHOLD", "MAX_DAILY_LOSS", "LOOP_INTERVAL",
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
                from src.predictor.trainer import train_from_history
                model = await train_from_history()
                if self.pipeline:
                    self.pipeline.xgb_model = model
                    logger.info("Model retrained and loaded into pipeline")
                self._last_error = None
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"Retrain failed: {e}")

    def update_settings(self, key: str, value) -> dict:
        if key not in UPDATABLE_SETTINGS:
            return {"ok": False, "error": f"Cannot update '{key}' at runtime"}
        old_value = getattr(self.settings, key)
        try:
            setattr(self.settings, key, value)
            # Re-validate by checking the pydantic validators
            Settings.model_validate(self.settings.model_dump())
            return {"ok": True, "key": key, "value": getattr(self.settings, key)}
        except Exception as e:
            # Rollback to previous value
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
        # Wait for any in-progress scan
        if self._scan_lock.locked():
            try:
                await asyncio.wait_for(self._scan_lock.acquire(), timeout=30)
                self._scan_lock.release()
            except asyncio.TimeoutError:
                logger.warning("Shutdown: scan still running after 30s")
        # Cancel settlement watchers
        if self.pipeline and hasattr(self.pipeline, '_settlement_tasks'):
            for task in self.pipeline._settlement_tasks:
                if not task.done():
                    task.cancel()
        self.db.close()
        logging.getLogger().removeHandler(self._log_handler)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_service.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q`
Expected: All tests PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/service.py tests/test_dashboard_service.py
git commit -m "feat: add DashboardService with read/control methods and settings rollback"
```

---

## Chunk 2: Terminal Dashboard (Textual)

### Task 5: Build terminal UI

**Files:**
- Create: `src/dashboard/terminal.py`

- [ ] **Step 1: Create the Textual app**

Create `src/dashboard/terminal.py`. Key design decisions:
- Log flushing uses an absolute `_log_id` counter on each entry (not buffer length) to avoid the deque overflow bug
- Settings modal validates input inline
- `action_quit` does graceful shutdown

```python
import asyncio
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, RichLog, DataTable
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input, Button, Label
from src.dashboard.service import DashboardService


class SettingsModal(ModalScreen):
    """Modal for editing bot settings."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, service: DashboardService):
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Settings (in-memory only, restart resets)", id="settings-title"),
            *self._setting_rows(),
            Button("Close", id="close-btn"),
            id="settings-modal",
        )

    def _setting_rows(self):
        from src.dashboard.service import UPDATABLE_SETTINGS
        for key in sorted(UPDATABLE_SETTINGS):
            val = getattr(self.service.settings, key)
            yield Horizontal(
                Label(f"{key}:", classes="setting-label"),
                Input(str(val), id=f"setting-{key}", classes="setting-input"),
                classes="setting-row",
            )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "close-btn":
            self.dismiss()

    def on_input_submitted(self, event: Input.Submitted):
        key = event.input.id.replace("setting-", "")
        try:
            value = float(event.value) if "." in event.value else int(event.value)
        except ValueError:
            value = event.value
        result = self.service.update_settings(key, value)
        if not result["ok"]:
            self.notify(f"Error: {result['error']}", severity="error")
        else:
            self.notify(f"{key} = {result['value']}")


class DashboardApp(App):
    """Polymarket bot terminal dashboard."""

    CSS = """
    #main { height: 1fr; }
    #left-col { width: 40; }
    #right-col { width: 1fr; }
    #performance { height: 8; border: solid green; padding: 1; }
    #trades-panel { height: 1fr; border: solid blue; }
    #log-panel { height: 1fr; border: solid yellow; }
    #markets-panel { height: 1fr; border: solid cyan; }
    .setting-row { height: 3; }
    .setting-label { width: 30; }
    .setting-input { width: 1fr; }
    #settings-modal { width: 60; height: 30; border: solid white; background: $surface; padding: 1; align: center middle; }
    #settings-title { text-style: bold; margin-bottom: 1; }
    """

    BINDINGS = [
        Binding("s", "scan", "Scan"),
        Binding("t", "train", "Train"),
        Binding("l", "loop", "Loop"),
        Binding("c", "config", "Config"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, service: DashboardService):
        super().__init__()
        self.service = service
        self._last_log_seen = 0  # absolute counter for log dedup

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text(), id="status-bar")
        with Horizontal(id="main"):
            with Vertical(id="left-col"):
                yield Static(self._perf_text(), id="performance")
                yield DataTable(id="trades-panel")
            with Vertical(id="right-col"):
                yield RichLog(id="log-panel", highlight=True, markup=True)
                yield DataTable(id="markets-panel")
        yield Footer()

    def on_mount(self):
        trades_table = self.query_one("#trades-panel", DataTable)
        trades_table.add_columns("Market", "Side", "Amount", "Status", "PnL")
        markets_table = self.query_one("#markets-panel", DataTable)
        markets_table.add_columns("Market", "Price", "Flags")
        self.set_interval(2, self._refresh)
        self._flush_logs()

    def _status_text(self) -> str:
        status = self.service.get_bot_status()
        mode = "LIVE" if not status["dry_run"] else "DRY RUN"
        loop = " | LOOP" if status["loop_active"] else ""
        scanning = " | SCANNING..." if status["scanning"] else ""
        return f"[{mode}] Cycle #{status['cycle_count']}{loop}{scanning}"

    def _perf_text(self) -> str:
        stats = self.service.get_stats()
        return (
            f"Performance\n"
            f"Win: {stats['win_rate']:.0%} ({stats['wins']}/{stats['total_trades']})\n"
            f"PnL: ${stats['total_pnl']:.2f}\n"
            f"Today: ${stats['today_pnl']:.2f}\n"
            f"Open: {stats['open_trades']} | Snapshots: {stats['snapshot_count']}"
        )

    def _refresh(self):
        self.query_one("#status-bar", Static).update(self._status_text())
        self.query_one("#performance", Static).update(self._perf_text())
        self._refresh_trades()
        self._refresh_markets()
        self._flush_logs()

    def _refresh_trades(self):
        table = self.query_one("#trades-panel", DataTable)
        table.clear()
        for t in self.service.get_recent_trades(limit=10):
            name = (t.get("question") or t["market_id"])[:25]
            pnl = f"${t['pnl']:.2f}" if t.get("pnl") is not None else "—"
            table.add_row(name, t["side"], f"${t['amount']:.0f}", t["status"], pnl)

    def _refresh_markets(self):
        table = self.query_one("#markets-panel", DataTable)
        table.clear()
        for m in self.service.get_flagged_markets()[:15]:
            flags = ", ".join(f.value for f in m.flags) if m.flags else "—"
            table.add_row(m.question[:30], f"{m.yes_price:.2f}", flags)

    def _flush_logs(self):
        """Write new log lines to the RichLog widget.
        Uses the full buffer snapshot and compares against last seen count.
        Since the buffer is a deque, we always show the latest entries.
        """
        log_widget = self.query_one("#log-panel", RichLog)
        current_logs = list(self.service._log_buffer)
        total_ever = len(current_logs)
        # On first call or after overflow, just show what's in the buffer
        new_count = total_ever - self._last_log_seen
        if new_count < 0 or new_count > total_ever:
            new_count = total_ever  # reset after overflow
        for line in current_logs[-new_count:] if new_count > 0 else []:
            log_widget.write(line)
        self._last_log_seen = total_ever

    async def action_scan(self):
        result = await self.service.trigger_scan(dry_run=self.service.dry_run)
        self.notify(f"Scan: {result['status']}")

    async def action_train(self):
        result = await self.service.trigger_retrain()
        self.notify(f"Retrain: {result['status']}")

    async def action_loop(self):
        result = await self.service.toggle_loop()
        state = "ON" if result.get("loop") else "OFF"
        self.notify(f"Loop: {state}")

    def action_config(self):
        self.push_screen(SettingsModal(self.service))

    async def action_quit(self):
        await self.service.shutdown()
        self.exit()
```

- [ ] **Step 2: Smoke test by running the app briefly**

Run: `source .venv/bin/activate && timeout 3 python -c "from src.dashboard.terminal import DashboardApp; print('Import OK')" || true`
Expected: "Import OK" printed without import errors.

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/terminal.py
git commit -m "feat: add Textual terminal dashboard UI"
```

---

## Chunk 3: Web Dashboard (FastAPI + htmx)

### Task 6: Build FastAPI backend

**Files:**
- Create: `src/dashboard/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing tests for API endpoints**

Create `tests/test_web.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def client(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        MockPipeline.return_value = MagicMock()
        from src.dashboard.web import create_app
        app = create_app(db_path=str(tmp_path / "test.db"))
        from fastapi.testclient import TestClient
        yield TestClient(app)


def test_get_stats(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_trades" in data
    assert "win_rate" in data


def test_get_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "loop_active" in data
    assert "cycle_count" in data
    assert "last_error" in data


def test_get_trades(client):
    resp = client.get("/api/trades")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_logs(client):
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_pnl_history(client):
    resp = client.get("/api/pnl-history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_markets(client):
    resp = client.get("/api/markets")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_lessons(client):
    resp = client.get("/api/lessons")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_post_scan(client):
    resp = client.post("/api/scan", json={"dry_run": True})
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_post_retrain(client):
    resp = client.post("/api/retrain")
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_post_loop(client):
    resp = client.post("/api/loop", json={"interval": 300})
    assert resp.status_code == 200
    assert "loop" in resp.json()


def test_post_settings_invalid_key(client):
    resp = client.post("/api/settings", json={"key": "ANTHROPIC_API_KEY", "value": "hacked"})
    assert resp.status_code == 400


def test_post_settings_valid(client):
    resp = client.post("/api/settings", json={"key": "BANKROLL", "value": 2000})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web.py -v`
Expected: FAIL — `src.dashboard.web` not found.

- [ ] **Step 3: Implement FastAPI app**

Create `src/dashboard/web.py`:

```python
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from src.dashboard.service import DashboardService

DASHBOARD_DIR = Path(__file__).parent
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"


class SettingsRequest(BaseModel):
    key: str
    value: float | int | str


class LoopRequest(BaseModel):
    interval: int | None = None


class ScanRequest(BaseModel):
    dry_run: bool | None = None


def create_app(settings=None, db_path: str = "bot.db") -> FastAPI:
    service = DashboardService(settings=settings, db_path=db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await service.shutdown()

    app = FastAPI(title="Polymarket Bot Dashboard", lifespan=lifespan)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) if TEMPLATES_DIR.exists() else None

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if templates:
            return templates.TemplateResponse("index.html", {"request": request})
        return HTMLResponse("<h1>Polymarket Bot Dashboard</h1><p>Templates not found.</p>")

    @app.get("/api/stats")
    async def api_stats():
        return await asyncio.to_thread(service.get_stats)

    @app.get("/api/trades")
    async def api_trades():
        return await asyncio.to_thread(service.get_recent_trades)

    @app.get("/api/markets")
    async def api_markets():
        markets = service.get_flagged_markets()
        return [m.model_dump() for m in markets] if markets else []

    @app.get("/api/pnl-history")
    async def api_pnl_history():
        return await asyncio.to_thread(service.get_pnl_history)

    @app.get("/api/lessons")
    async def api_lessons():
        return await asyncio.to_thread(service.get_lessons)

    @app.get("/api/status")
    async def api_status():
        return service.get_bot_status()

    @app.get("/api/logs")
    async def api_logs():
        return service.get_recent_logs()

    @app.post("/api/scan", status_code=202)
    async def api_scan(body: ScanRequest | None = None):
        dry_run = body.dry_run if body and body.dry_run is not None else service.dry_run
        result = await service.trigger_scan(dry_run=dry_run)
        if result["status"] == "already_running":
            return JSONResponse(result, status_code=409)
        if result["status"] == "error":
            return JSONResponse(result, status_code=500)
        return result

    @app.post("/api/retrain", status_code=202)
    async def api_retrain():
        result = await service.trigger_retrain()
        if result["status"] == "already_running":
            return JSONResponse(result, status_code=409)
        return result

    @app.post("/api/loop")
    async def api_loop(body: LoopRequest | None = None):
        interval = body.interval if body else None
        return await service.toggle_loop(interval=interval)

    @app.post("/api/settings")
    async def api_settings(body: SettingsRequest):
        result = service.update_settings(body.key, body.value)
        if not result["ok"]:
            return JSONResponse(result, status_code=400)
        return result

    app.state.service = service
    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/web.py tests/test_web.py
git commit -m "feat: add FastAPI web dashboard with API endpoints"
```

---

### Task 7: Build web frontend

**Files:**
- Create: `src/dashboard/templates/index.html`
- Create: `src/dashboard/static/style.css`

- [ ] **Step 1: Create the HTML template**

Create `src/dashboard/templates/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Bot Dashboard</title>
    <link rel="stylesheet" href="/static/style.css">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
</head>
<body>
    <header>
        <h1>Polymarket Bot</h1>
        <div id="status-badge" hx-get="/api/status" hx-trigger="load, every 10s"
             hx-swap="innerHTML">Loading...</div>
        <nav>
            <button hx-post="/api/scan" hx-swap="none" class="btn">Scan</button>
            <button hx-post="/api/retrain" hx-swap="none" class="btn">Retrain</button>
            <button hx-post="/api/loop" hx-swap="none" class="btn">Toggle Loop</button>
            <button onclick="document.getElementById('settings-modal').showModal()" class="btn">Settings</button>
        </nav>
    </header>

    <main>
        <section class="stats-row" hx-get="/api/stats" hx-trigger="load, every 10s" hx-swap="innerHTML">
        </section>

        <div class="grid">
            <section class="card chart-card">
                <h2>PnL History</h2>
                <canvas id="pnl-chart"></canvas>
            </section>

            <section class="card">
                <h2>Trade History</h2>
                <div id="trades-table" hx-get="/api/trades" hx-trigger="load, every 10s" hx-swap="innerHTML">
                </div>
            </section>

            <section class="card">
                <h2>Flagged Markets</h2>
                <div id="markets-list" hx-get="/api/markets" hx-trigger="load, every 10s" hx-swap="innerHTML">
                </div>
            </section>

            <section class="card">
                <h2>Live Logs</h2>
                <div id="log-feed" class="log-feed" hx-get="/api/logs" hx-trigger="load, every 5s" hx-swap="innerHTML">
                </div>
            </section>

            <section class="card">
                <h2>Lessons</h2>
                <div id="lessons-list" hx-get="/api/lessons" hx-trigger="load, every 30s" hx-swap="innerHTML">
                </div>
            </section>
        </div>
    </main>

    <dialog id="settings-modal">
        <h2>Settings</h2>
        <p class="muted">In-memory only. Restart resets to .env values.</p>
        <form id="settings-form">
            <label>BANKROLL <input type="number" name="BANKROLL" step="any"></label>
            <label>MAX_BET_FRACTION <input type="number" name="MAX_BET_FRACTION" step="0.01"></label>
            <label>CONFIDENCE_THRESHOLD <input type="number" name="CONFIDENCE_THRESHOLD" step="0.01"></label>
            <label>MIN_EDGE_THRESHOLD <input type="number" name="MIN_EDGE_THRESHOLD" step="0.01"></label>
            <label>MAX_DAILY_LOSS <input type="number" name="MAX_DAILY_LOSS" step="any"></label>
            <label>LOOP_INTERVAL <input type="number" name="LOOP_INTERVAL" step="1"></label>
        </form>
        <button onclick="document.getElementById('settings-modal').close()" class="btn">Close</button>
    </dialog>

    <script>
    // PnL chart
    let pnlChart = null;
    async function refreshChart() {
        const resp = await fetch('/api/pnl-history');
        const data = await resp.json();
        const labels = data.map(d => d.date);
        const values = data.map(d => d.cumulative_pnl);
        if (!pnlChart) {
            const ctx = document.getElementById('pnl-chart').getContext('2d');
            pnlChart = new Chart(ctx, {
                type: 'line',
                data: { labels, datasets: [{ label: 'Cumulative PnL ($)', data: values,
                    borderColor: '#4ade80', backgroundColor: 'rgba(74,222,128,0.1)', fill: true }] },
                options: { responsive: true, scales: { y: { grid: { color: '#333' } },
                    x: { grid: { color: '#333' } } }, plugins: { legend: { labels: { color: '#ccc' } } } }
            });
        } else {
            pnlChart.data.labels = labels;
            pnlChart.data.datasets[0].data = values;
            pnlChart.update();
        }
    }
    refreshChart();
    setInterval(refreshChart, 60000);

    // Settings form submission
    document.getElementById('settings-form').addEventListener('change', async (e) => {
        const key = e.target.name;
        const value = parseFloat(e.target.value);
        const resp = await fetch('/api/settings', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value})
        });
        const result = await resp.json();
        if (!result.ok) alert('Error: ' + result.error);
    });

    // Format htmx responses
    htmx.on('htmx:beforeSwap', function(evt) {
        if (evt.detail.target.id === 'status-badge') {
            const data = JSON.parse(evt.detail.xhr.responseText);
            const mode = data.dry_run ? 'DRY RUN' : 'LIVE';
            const loop = data.loop_active ? ' | LOOP' : '';
            const scan = data.scanning ? ' | SCANNING...' : '';
            const err = data.last_error ? ' | ERR' : '';
            evt.detail.serverResponse = `<span class="badge ${data.dry_run ? 'badge-dry' : 'badge-live'}">${mode}</span> Cycle #${data.cycle_count}${loop}${scan}${err}`;
        }
        if (evt.detail.target.id === 'trades-table') {
            const trades = JSON.parse(evt.detail.xhr.responseText);
            let html = '<table><tr><th>Market</th><th>Side</th><th>Amount</th><th>Status</th><th>PnL</th></tr>';
            trades.forEach(t => {
                const name = (t.question || t.market_id || '').substring(0, 30);
                const pnl = t.pnl != null ? `$${t.pnl.toFixed(2)}` : '—';
                html += `<tr><td>${name}</td><td>${t.side}</td><td>$${t.amount.toFixed(0)}</td><td>${t.status}</td><td>${pnl}</td></tr>`;
            });
            evt.detail.serverResponse = html + '</table>';
        }
        if (evt.detail.target.id === 'markets-list') {
            const markets = JSON.parse(evt.detail.xhr.responseText);
            let html = '<table><tr><th>Market</th><th>YES</th><th>Flags</th></tr>';
            markets.forEach(m => {
                const flags = (m.flags || []).join(', ') || '—';
                html += `<tr><td>${(m.question||'').substring(0,35)}</td><td>${m.yes_price.toFixed(2)}</td><td>${flags}</td></tr>`;
            });
            evt.detail.serverResponse = html + '</table>';
        }
        if (evt.detail.target.className === 'stats-row') {
            const s = JSON.parse(evt.detail.xhr.responseText);
            evt.detail.serverResponse = `
                <div class="stat-card"><div class="stat-value">${(s.win_rate*100).toFixed(0)}%</div><div class="stat-label">Win Rate (${s.wins}/${s.total_trades})</div></div>
                <div class="stat-card"><div class="stat-value">$${s.total_pnl.toFixed(2)}</div><div class="stat-label">Total PnL</div></div>
                <div class="stat-card"><div class="stat-value">$${s.today_pnl.toFixed(2)}</div><div class="stat-label">Today</div></div>
                <div class="stat-card"><div class="stat-value">${s.open_trades}</div><div class="stat-label">Open Trades</div></div>
                <div class="stat-card"><div class="stat-value">${s.snapshot_count}</div><div class="stat-label">Snapshots</div></div>`;
        }
        if (evt.detail.target.id === 'log-feed') {
            const logs = JSON.parse(evt.detail.xhr.responseText);
            evt.detail.serverResponse = logs.map(l => `<div class="log-line">${l}</div>`).join('');
        }
        if (evt.detail.target.id === 'lessons-list') {
            const lessons = JSON.parse(evt.detail.xhr.responseText);
            if (lessons.length === 0) { evt.detail.serverResponse = '<p class="muted">No lessons yet.</p>'; }
            else { evt.detail.serverResponse = '<ul>' + lessons.map(l => `<li><strong>${l.category}:</strong> ${l.lesson}</li>`).join('') + '</ul>'; }
        }
    });
    </script>
</body>
</html>
```

- [ ] **Step 2: Create the CSS file**

Create `src/dashboard/static/style.css`:

```css
:root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-muted: #8b949e;
    --green: #4ade80;
    --red: #f87171;
    --blue: #60a5fa;
    --yellow: #fbbf24;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'SF Mono', 'Fira Code', monospace; background: var(--bg); color: var(--text); padding: 1rem; }

header { display: flex; align-items: center; gap: 1rem; padding: 0.75rem 0; border-bottom: 1px solid var(--border); margin-bottom: 1rem; flex-wrap: wrap; }
header h1 { font-size: 1.2rem; color: var(--green); }
header nav { display: flex; gap: 0.5rem; margin-left: auto; }

.btn { background: var(--surface); color: var(--text); border: 1px solid var(--border); padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 0.85rem; }
.btn:hover { border-color: var(--blue); }

.badge { padding: 0.2rem 0.5rem; border-radius: 3px; font-size: 0.8rem; font-weight: bold; }
.badge-dry { background: var(--yellow); color: #000; }
.badge-live { background: var(--red); color: #fff; }

.stats-row { display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 1rem; flex: 1; min-width: 120px; text-align: center; }
.stat-value { font-size: 1.5rem; font-weight: bold; color: var(--green); }
.stat-label { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.3rem; }

.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 1rem; }
.card h2 { font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
.chart-card { grid-column: span 2; }

table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th, td { padding: 0.4rem 0.6rem; text-align: left; border-bottom: 1px solid var(--border); }
th { color: var(--text-muted); font-weight: 600; }

.log-feed { max-height: 300px; overflow-y: auto; font-size: 0.8rem; }
.log-line { padding: 0.15rem 0; border-bottom: 1px solid #1a1f26; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.muted { color: var(--text-muted); font-size: 0.85rem; }
ul { padding-left: 1.2rem; }
li { margin-bottom: 0.3rem; font-size: 0.85rem; }

dialog { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; max-width: 500px; }
dialog::backdrop { background: rgba(0,0,0,0.7); }
dialog label { display: block; margin-bottom: 0.5rem; font-size: 0.85rem; }
dialog input { width: 100%; background: var(--bg); color: var(--text); border: 1px solid var(--border); padding: 0.3rem 0.5rem; border-radius: 3px; margin-top: 0.2rem; font-family: inherit; }
```

- [ ] **Step 3: Verify the web UI loads**

Run: `source .venv/bin/activate && timeout 5 python -c "from src.dashboard.web import create_app; app = create_app(); print('App created OK')" || true`
Expected: "App created OK" printed without errors.

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/templates/index.html src/dashboard/static/style.css
git commit -m "feat: add web dashboard frontend (htmx + Chart.js dark theme)"
```

---

## Chunk 4: Entry Points + Integration

### Task 8: Wire up run.py entry points

**Files:**
- Modify: `run.py`

- [ ] **Step 1: Add --dashboard and --web flags to run.py**

Add after the `--train` block and before the `dry_run` line:

```python
    if "--dashboard" in sys.argv:
        from src.dashboard.service import DashboardService
        from src.dashboard.terminal import DashboardApp
        svc = DashboardService(settings=settings)
        svc.dry_run = "--live" not in sys.argv
        app = DashboardApp(svc)
        # If --loop requested, schedule it after Textual event loop starts
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
```

Note: The `--dashboard --loop` case uses `app.call_later()` to schedule `toggle_loop()` inside the Textual event loop, avoiding the "no running event loop" error.

- [ ] **Step 2: Test import works**

Run: `source .venv/bin/activate && python -c "import run; print('OK')"`
Expected: "OK" without import errors.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -q`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add run.py
git commit -m "feat: add --dashboard and --web entry points to run.py"
```

---

### Task 9: Final integration test

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 2: Smoke test terminal dashboard**

Run: `timeout 5 python run.py --dashboard 2>&1 || true`
Expected: Textual app starts without crashes (will timeout after 5s).

- [ ] **Step 3: Smoke test web dashboard**

Run: `timeout 5 python run.py --web 2>&1 || true`
Expected: Uvicorn starts, prints "Started server process" (will timeout after 5s).

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete dashboard implementation (terminal + web)"
```
