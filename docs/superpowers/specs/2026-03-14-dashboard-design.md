# Polymarket Bot Dashboard — Design Spec

## Overview

Dual-frontend dashboard for the polymarket-bot: a terminal UI (Textual) and a web UI (FastAPI + htmx). Both share a common service layer and provide real-time monitoring, historical analytics, and bot control.

## Architecture

```
DashboardService (src/dashboard/service.py)
├── Terminal UI (Textual) — src/dashboard/terminal.py
└── Web UI (FastAPI + htmx) — src/dashboard/web.py
```

The dashboard runs the bot in-process. No separate bot process to manage. The service holds a reference to the Pipeline and manages an optional background loop task.

## Shared Service Layer

`DashboardService` wraps all DB queries and bot control into a single class.

### Read Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get_stats()` | dict | Win rate, total PnL, today's PnL, trade counts, open trades, snapshot count |
| `get_recent_trades(limit=20)` | list[dict] | Last N trades with side, amount, price, status, PnL |
| `get_flagged_markets()` | list[ScannedMarket] | Markets from most recent scan, cached |
| `get_pnl_history()` | list[dict] | Daily PnL series (date, cumulative_pnl) for charting |
| `get_lessons(category=None)` | list[dict] | Postmortem insights, optionally filtered |
| `get_bot_status()` | dict | running/stopped, loop mode, dry_run, last cycle time, cycle count |

### Control Methods

| Method | Action |
|--------|--------|
| `trigger_scan(dry_run=True)` | Run one pipeline cycle asynchronously |
| `trigger_retrain()` | Retrain XGBoost model on historical data |
| `update_settings(key, value)` | Live-update bankroll, thresholds, etc. |
| `toggle_loop(interval=None)` | Start/stop continuous cycling |

### Internal State

- `pipeline: Pipeline` — the bot pipeline instance
- `_loop_task: asyncio.Task | None` — background loop if active
- `_last_scan_results: list[ScannedMarket]` — cached from last cycle
- `_cycle_count: int` — total cycles run this session
- `_started_at: datetime` — session start time

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
│   Recent Trades    │   Top Markets                │
│   BTC>100k YES $42 │   BTC>100k  0.55 HIGH_VOL   │
│   ETH>5k  NO  $25  │   ETH>5k   0.35 WIDE_SPREAD│
│   ...              │   ...                        │
├────────────────────┴─────────────────────────────┤
│ [s]can [t]rain [l]oop [q]uit                      │
└──────────────────────────────────────────────────┘
```

### Panels

- **Status bar**: Bot mode (dry-run/live), running state, cycle count, time since last cycle
- **Performance**: Win rate, PnL (total + today), open trade count
- **Recent Trades**: Last 10 trades — market, side, amount, status, PnL
- **Live Feed**: Scrolling log of cycle activity (scans, predictions, risk decisions)
- **Top Markets**: Current flagged markets with prices and flags
- **Footer**: Keyboard shortcuts for control actions

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `s` | Trigger single scan cycle |
| `t` | Retrain XGBoost model |
| `l` | Toggle loop mode on/off |
| `q` | Quit dashboard |

### Refresh

- Stats and trades refresh after each cycle completes
- Live feed updates in real-time via log handler

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

| Route | Method | Description |
|-------|--------|-------------|
| `GET /` | — | Serve main page |
| `GET /api/stats` | GET | Stats JSON |
| `GET /api/trades` | GET | Recent trades JSON |
| `GET /api/markets` | GET | Flagged markets JSON |
| `GET /api/pnl-history` | GET | Daily PnL series JSON |
| `GET /api/lessons` | GET | Lessons JSON |
| `GET /api/status` | GET | Bot status JSON |
| `POST /api/scan` | POST | Trigger scan cycle |
| `POST /api/retrain` | POST | Trigger model retrain |
| `POST /api/loop` | POST | Toggle loop mode |
| `POST /api/settings` | POST | Update settings |

### Frontend

- Single `index.html` template with Jinja2
- htmx for auto-refresh (polls `/api/stats` and `/api/status` every 30s)
- Chart.js via CDN for PnL line chart
- Minimal `style.css` — clean, dark theme to match terminal aesthetic
- No JS framework, no npm, no build step

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

`tests/test_dashboard.py`:

- Service returns correct stats from DB
- Service caches scan results
- Control methods (trigger_scan, toggle_loop) work
- Bot status reflects current state
- Settings update validates input

## Constraints

- Dashboard and bot run in the same process — no IPC complexity
- SQLite is single-writer, so control actions queue behind active cycles
- Web UI is localhost-only by default (no auth needed)
- Terminal UI requires a terminal that supports 256 colors (most modern terminals)
