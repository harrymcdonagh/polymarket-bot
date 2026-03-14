# Polymarket Bot Dashboard — Design Spec

## Overview

Dual-frontend dashboard for the polymarket-bot: a terminal UI (Textual) and a web UI (FastAPI + htmx). Both share a common service layer and provide real-time monitoring, historical analytics, and bot control.

## Architecture

```
DashboardService (src/dashboard/service.py)
├── Terminal UI (Textual) — src/dashboard/terminal.py
└── Web UI (FastAPI + htmx) — src/dashboard/web.py
```

The dashboard runs the bot in-process. `DashboardService.__init__` creates the Pipeline. If Pipeline init fails (e.g., missing API keys), the dashboard still renders in degraded mode — read-only stats work, control actions return errors.

The service holds a reference to the Pipeline and manages an optional background loop task.

## Shared Service Layer

`DashboardService` wraps all DB queries and bot control into a single class.

### Read Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get_stats()` | dict | Win rate, total PnL, today's PnL, trade counts, open trades, snapshot count |
| `get_recent_trades(limit=20)` | list[dict] | Last N trades with market name, side, amount, price, status, PnL |
| `get_flagged_markets()` | list[ScannedMarket] | Markets from most recent scan, cached |
| `get_pnl_history()` | list[dict] | Daily PnL series (date, daily_pnl, cumulative_pnl) for charting |
| `get_lessons(category=None)` | list[dict] | Postmortem insights, optionally filtered |
| `get_bot_status()` | dict | running/stopped, loop mode, dry_run, last cycle time, cycle count |
| `get_recent_logs(limit=50)` | list[str] | Recent log lines from in-memory ring buffer |

### Control Methods

| Method | Action |
|--------|--------|
| `trigger_scan(dry_run=True)` | Run one pipeline cycle asynchronously. Returns immediately. Mutex prevents concurrent scans. |
| `trigger_retrain()` | Retrain XGBoost model. Mutex prevents concurrent retrains. |
| `update_settings(key, value)` | In-memory only update to Settings object. See Updatable Settings below. |
| `toggle_loop(interval=None)` | Start/stop continuous cycling. Interval defaults to `LOOP_INTERVAL` from settings. |

### Updatable Settings

Only these keys can be updated at runtime (in-memory, not persisted to `.env`):

| Key | Validation |
|-----|-----------|
| `BANKROLL` | Must be > 0 |
| `MAX_BET_FRACTION` | Must be 0 < x <= 1 |
| `CONFIDENCE_THRESHOLD` | Must be 0 <= x <= 1 |
| `MIN_EDGE_THRESHOLD` | Must be >= 0 |
| `MAX_DAILY_LOSS` | Must be > 0 |
| `LOOP_INTERVAL` | Must be >= 30 |

Updates are validated using the existing pydantic field validators. Invalid values return an error message.

### Internal State

- `pipeline: Pipeline` — the bot pipeline instance (may be None if init failed)
- `_loop_task: asyncio.Task | None` — background loop if active
- `_last_scan_results: list[ScannedMarket]` — cached from last cycle
- `_cycle_count: int` — total cycles run this session
- `_started_at: datetime` — session start time
- `_scan_lock: asyncio.Lock` — prevents concurrent scans/retrains
- `_log_buffer: collections.deque` — ring buffer of recent log lines (maxlen=200)

### Database Changes

New DB method needed for PnL charting:

```python
def get_pnl_history(self) -> list[dict]:
    """Daily PnL series for charting."""
    # SELECT DATE(settled_at) as date, SUM(pnl) as daily_pnl
    # FROM trades WHERE status='settled'
    # GROUP BY DATE(settled_at) ORDER BY date
```

Trade name resolution: `get_recent_trades()` joins `trades` with `market_snapshots` on `market_id = condition_id` to get human-readable `question` field. Falls back to showing truncated `market_id` if no snapshot found.

### SQLite Concurrency

All DB access from the web server is wrapped in `asyncio.to_thread()` to avoid blocking the event loop and prevent SQLite threading issues. The `Database` class connection is per-thread via `threading.local()` storage.

### Log Capture

A custom `logging.Handler` subclass (`DashboardLogHandler`) appends formatted log lines to the `_log_buffer` deque. Installed on the root logger at dashboard startup. Both UIs read from this buffer:
- Terminal: `RichLog` widget polls buffer on a 1s timer
- Web: `/api/logs` endpoint returns latest entries, polled by htmx every 5s

## Terminal Dashboard (Textual)

### Layout

```
┌─────────────────── Status Bar ───────────────────┐
│ [DRY RUN] Running | Cycle #5 | Last: 2m ago      │
├────────────────────┬─────────────────────────────┤
│   Performance      │   Live Feed                  │
│   Win: 65% (13/20) │   [14:32] Scanned 686 mkts  │
│   PnL: +$142.50    │   [14:32] Evaluating 10...   │
│   Today: +$23.00   │   [14:33] BTC > 100k: YES    │
│   Open: 3          │   [14:33] Edge 12%, conf 0.8 │
│                    │   [14:33] APPROVED $42.50     │
├────────────────────┤                              │
│   Recent Trades    │   Flagged Markets            │
│   BTC>100k YES $42 │   BTC>100k  0.55 HIGH_VOL   │
│   ETH>5k  NO  $25  │   ETH>5k   0.35 WIDE_SPREAD│
│   ...              │   ...                        │
├────────────────────┴─────────────────────────────┤
│ [s]can [t]rain [l]oop [c]onfig [q]uit             │
└──────────────────────────────────────────────────┘
```

### Panels

- **Status bar**: Bot mode (dry-run/live), running state, cycle count, time since last cycle
- **Performance**: Win rate, PnL (total + today), open trade count
- **Recent Trades**: Last 10 trades — market name, side, amount, status, PnL
- **Live Feed**: Scrolling log of cycle activity via `DashboardLogHandler`
- **Flagged Markets**: Current flagged markets with prices and flags
- **Footer**: Keyboard shortcuts for control actions

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `s` | Trigger single scan cycle |
| `t` | Retrain XGBoost model |
| `l` | Toggle loop mode on/off |
| `c` | Open settings panel (modal with editable fields) |
| `q` | Graceful quit (cancels loop task, waits for active cycle, closes DB) |

### Refresh

- Stats and trades refresh after each cycle completes
- Live feed updates on 1s timer from log buffer

## Web Dashboard (FastAPI + htmx)

### Layout

```
┌──────────────────────────────────────────────────┐
│  Header: Status badge | [Scan] [Retrain] [Loop]  │
│                                    [Settings ⚙]  │
├──────────┬──────────┬────────────────────────────┤
│ Win Rate │ PnL      │  PnL Chart (Chart.js)      │
│  65%     │ +$142.50 │  ────/\──/\──────           │
│          │          │                             │
├──────────┴──────────┤                             │
│ Trade History       │  Flagged Markets            │
│ ┌────┬────┬───┬───┐ │  BTC>100k 0.55 HIGH_VOL   │
│ │mkt │side│amt│pnl│ │  ETH>5k   0.35 WIDE_SPREAD│
│ │... │... │...│...│ │                             │
│ └────┴────┴───┴───┘ │  Lessons                   │
│                     │  - Check vol before bet     │
└─────────────────────┴────────────────────────────┘
```

### Endpoints

| Route | Method | Body | Description |
|-------|--------|------|-------------|
| `GET /` | — | — | Serve main page |
| `GET /api/stats` | GET | — | Stats JSON |
| `GET /api/trades` | GET | — | Recent trades JSON (with market names) |
| `GET /api/markets` | GET | — | Flagged markets JSON |
| `GET /api/pnl-history` | GET | — | Daily PnL series JSON |
| `GET /api/lessons` | GET | — | Lessons JSON |
| `GET /api/status` | GET | — | Bot status JSON + recent errors |
| `GET /api/logs` | GET | — | Recent log lines JSON |
| `POST /api/scan` | POST | `{"dry_run": true}` | Trigger scan. Returns `202 {status: "started"}`. Dry-run defaults to current mode. |
| `POST /api/retrain` | POST | — | Trigger retrain. Returns `202 {status: "started"}` or `409` if already running. |
| `POST /api/loop` | POST | `{"interval": 300}` | Toggle loop. Interval optional, defaults to `LOOP_INTERVAL`. |
| `POST /api/settings` | POST | `{"key": "BANKROLL", "value": 2000}` | Update setting. Returns `200` or `400` with validation error. |

### Error Handling

- Control endpoints return structured errors: `{"error": "message"}`
- `409 Conflict` if scan/retrain already in progress
- `400 Bad Request` for invalid settings
- `/api/status` includes `last_error` field (last cycle error message, if any)

### Frontend

- Single `index.html` template with Jinja2
- htmx polls `/api/stats` and `/api/status` every 10s, `/api/logs` every 5s
- Chart.js via CDN for PnL line chart
- Minimal `style.css` — clean, dark theme
- No JS framework, no npm, no build step
- Control buttons disabled while scan/retrain is in progress (via htmx swap from status response)

### Security

- Binds to `127.0.0.1` only by default (not `0.0.0.0`)
- No authentication required for localhost
- CORS disabled (same-origin only)

## Graceful Shutdown

Both UIs handle shutdown cleanly:

1. Cancel `_loop_task` if active
2. Wait for any in-progress scan cycle to complete (with 30s timeout)
3. Cancel pending settlement watchers
4. Close DB connection
5. Exit

Terminal: triggered by `q` key. Web: triggered by SIGINT/SIGTERM.

## File Structure

```
src/dashboard/
├── __init__.py
├── service.py          # DashboardService
├── terminal.py         # Textual app
├── web.py              # FastAPI app + API routes
├── templates/
│   └── index.html      # Web dashboard page
└── static/
    └── style.css       # Web dashboard styles
```

## Entry Points

Added to `run.py`:

```
python run.py --dashboard        # Terminal UI
python run.py --web              # Web UI on localhost:8050
python run.py --web --live       # Web UI with live trading enabled
python run.py --dashboard --loop # Terminal UI with auto-loop
```

Existing flags (`--live`, `--loop`, `--train`, `--interval=N`) compose with dashboard flags.

## Dependencies

New additions to `pyproject.toml`:

- `textual>=0.50` — terminal UI framework
- `fastapi>=0.110` — web framework
- `uvicorn>=0.27` — ASGI server
- `jinja2>=3.1` — HTML templating

Chart.js loaded via CDN (no install needed).

## Testing

`tests/test_dashboard.py` — Service layer:

- Service returns correct stats from DB
- Service caches scan results
- Control methods (trigger_scan, toggle_loop) work
- Scan mutex prevents concurrent scans
- Bot status reflects current state
- Settings update validates input and rejects invalid keys
- PnL history returns correct daily aggregation
- Trade names resolved from snapshots

`tests/test_web.py` — FastAPI endpoints (using TestClient):

- `GET /api/stats` returns 200 with expected shape
- `POST /api/scan` returns 202
- `POST /api/scan` returns 409 when already running
- `POST /api/settings` returns 400 for invalid values
- `GET /api/logs` returns recent log entries

## Constraints

- Dashboard and bot run in the same process — no IPC complexity
- SQLite accessed via `asyncio.to_thread()` for web, direct for terminal
- Web UI is `127.0.0.1` only by default
- Terminal UI requires a terminal that supports 256 colors (most modern terminals)
- Settings changes are in-memory only — restart resets to `.env` values
