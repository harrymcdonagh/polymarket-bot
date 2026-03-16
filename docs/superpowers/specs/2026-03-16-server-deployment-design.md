# Server Deployment Design — Polymarket Bot

**Date:** 2026-03-16
**Status:** Approved

## Overview

Deploy the Polymarket prediction bot to a DigitalOcean droplet for 24/7 unattended operation in dry-run mode. The bot continuously scans markets, researches, predicts, logs hypothetical trades, monitors their resolution, and learns from outcomes via postmortem analysis. Telegram notifications keep the user informed. A web dashboard is accessible via direct IP.

## Infrastructure

- **Provider:** DigitalOcean
- **Droplet:** $12/mo (2GB RAM, 1 vCPU, Ubuntu 24.04)
- **Firewall:** UFW — allow SSH (22) and web dashboard (8050)
- **User:** Dedicated `polymarket` system user (non-root)
- **Memory note:** Transformer sentiment model (~500MB-1GB RAM) is loaded by the bot process. 2GB droplet should suffice with three lightweight Python processes, but monitor with `htop`. If memory is tight, disable transformer sentiment (`USE_TRANSFORMER=false`) and fall back to VADER only.

## Directory Structure

```
/opt/polymarket-bot/
├── src/                      # Application code (git clone)
├── .env                      # API keys & config (not in git)
├── data/
│   └── polymarket.db         # SQLite database (persisted)
└── venv/                     # Python virtual environment
```

## Systemd Services

### 1. `polymarket-bot.service` — Main Bot Loop

- **Command:** `python run.py --loop --interval=600`
- **Mode:** Dry-run (no real trades)
- **Cycle:** Every 10 minutes — scan, research, predict, log dry-run trades
- **Restart:** Auto-restart on crash (5s delay)
- **Boot:** Enabled via `systemctl enable`
- **Env:** Loaded via `EnvironmentFile=/opt/polymarket-bot/.env`

### 2. `polymarket-web.service` — Web Dashboard

- **Command:** `python run.py --web --host 0.0.0.0`
- **Listens:** `0.0.0.0:8050` (code currently defaults to `127.0.0.1` — must add `--host` flag or change default)
- **Access:** `http://<droplet-ip>:8050`
- **Separate service** so bot and dashboard can restart independently
- **Restart:** Auto-restart on crash
- **Boot:** Enabled via `systemctl enable`

### 3. `polymarket-settler.service` — Settlement Monitor

- **Command:** `python run.py --settle --interval=3600`
- **Cycle:** Every hour
- **Purpose:** Close the feedback loop on dry-run trades
- **Restart:** Auto-restart on crash
- **Boot:** Enabled via `systemctl enable`

**Settlement flow:**
1. Query DB for trades with `status='dry_run'` where market is unresolved
2. For each trade, check Polymarket API for market resolution
3. When a market settles:
   - Record outcome (YES/NO)
   - Calculate hypothetical P&L
   - Update trade: `status='dry_run_settled'`, store `resolved_outcome`, `hypothetical_pnl`, `resolved_at`
   - Run postmortem analysis on losing trades (existing postmortem system)
   - Extract and store lessons to `lessons` table
4. Send Telegram notification with result

## Telegram Notifications

**New module:** `src/notifications/telegram.py`

**Sends via Telegram Bot API using a bot created with @BotFather.**

**Environment variables:**
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `TELEGRAM_CHAT_ID` — user's chat ID

**Notification triggers:**
| Event | Message Example |
|---|---|
| Dry-run trade logged | "Would have bought YES on [market] at $0.42, edge 12%" |
| Pipeline error | "Research pipeline failed: NewsAPI timeout" |
| Market resolved | "Market resolved: [name] → YES. Prediction: 0.72 at $0.42. Hypothetical P&L: +$X" |
| Daily summary | "Today: 50 markets scanned, 3 trades flagged, top edge: 15% on [market]" |
| Bot startup/restart | "Bot started" / "Bot restarted after crash" |

**Integration:** Hooks into the pipeline's existing `status_callback` mechanism. A notification listener watches for key events and dispatches Telegram messages.

**Daily summary trigger:** The settler service tracks the last summary timestamp. On each hourly run, if it's past midnight UTC and no summary has been sent today, it compiles and sends the daily summary.

## Database Changes

Add columns to the `trades` table:

| Column | Type | Purpose |
|---|---|---|
| `resolved_outcome` | TEXT (nullable) | "YES" or "NO" — the actual market result |
| `hypothetical_pnl` | REAL (nullable) | What the trade would have made/lost |
| `resolved_at` | TEXT (nullable) | ISO timestamp of resolution |

| `predicted_prob` | REAL (nullable) | Bot's predicted probability at trade time (needed for postmortem) |

No new tables. Reuses existing `postmortems` and `lessons` tables for the learning loop.

**SQLite concurrency:** Three services access the same database. Enable WAL mode and set a 30-second busy timeout on all connections:
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=30000")
```

**Database path:** Add `DB_PATH` setting to `src/config.py` (default: `data/polymarket.db`). All three services must use the same database file. Current code defaults to `bot.db` in the working directory — this must be changed.

**Migrations:** Add a `db.migrate()` method that checks for missing columns and adds them via `ALTER TABLE`. Called on startup before any queries. `CREATE TABLE IF NOT EXISTS` does not add columns to existing tables.

## New Code

| File | Purpose |
|---|---|
| `src/notifications/telegram.py` | Telegram Bot API client, message formatting, send methods |
| `src/notifications/__init__.py` | Package init |
| `src/settler/settler.py` | Settlement monitor — checks market resolution, calculates P&L, triggers postmortem |
| `src/settler/__init__.py` | Package init |
| `deploy/polymarket-bot.service` | Systemd unit for main bot loop |
| `deploy/polymarket-web.service` | Systemd unit for web dashboard |
| `deploy/polymarket-settler.service` | Systemd unit for settlement monitor |
| `deploy/setup.sh` | Server setup script: installs `python3 python3-venv python3-pip git ufw`, creates `polymarket` user, sets up venv, configures UFW (ports 22, 8050), installs + enables systemd units |

## Modified Code

| File | Change |
|---|---|
| `src/db.py` | Add settlement columns + query methods; WAL mode + busy_timeout; `migrate()` method; use `DB_PATH` config |
| `src/pipeline.py` | Integrate Telegram notification listener into status_callback |
| `src/config.py` | Add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DB_PATH`, `DASHBOARD_PASSWORD` settings |
| `run.py` | Add `--settle` CLI flag with async loop, `--host` flag for web; wire `DB_PATH` |
| `src/dashboard/web.py` | Add HTTP Basic Auth middleware using `DASHBOARD_PASSWORD` |
| `.env.example` | Add Telegram config variables |

## Logging

All three services log to `journald` by default. Configure log retention to prevent disk bloat:
- Set `SystemMaxUse=500M` in `/etc/systemd/journald.conf`
- View logs: `journalctl -u polymarket-bot -f` (follow), `-u polymarket-settler --since today`

## Backups

Daily SQLite backup via cron:
```bash
# /etc/cron.daily/polymarket-backup
sqlite3 /opt/polymarket-bot/data/polymarket.db ".backup /opt/polymarket-bot/data/backup-$(date +%Y%m%d).db"
find /opt/polymarket-bot/data/ -name "backup-*.db" -mtime +7 -delete
```
Keeps 7 days of backups. Optional: push to DigitalOcean Spaces for off-host redundancy.

## Deployment Workflow

1. SSH into droplet
2. `cd /opt/polymarket-bot && git pull`
3. `source venv/bin/activate && pip install -e .`
4. `sudo systemctl restart polymarket-bot polymarket-web polymarket-settler`

## Security

- Bot runs as unprivileged `polymarket` user
- `.env` file is `chmod 600`, owned by `polymarket` user
- UFW firewall: only ports 22 and 8050 open
- No HTTPS (personal dashboard, accessed via IP)
- **Dashboard auth:** HTTP Basic Auth via `DASHBOARD_PASSWORD` env var. If set, all dashboard routes require authentication. Simple middleware check.
- Private keys and API tokens never committed to git
- `.env` format: use bare `KEY=value` (no quotes) for systemd `EnvironmentFile` compatibility

## Success Criteria

- Bot runs 24/7 without manual intervention
- Auto-restarts after crashes or droplet reboots
- Dry-run trades are logged and tracked to resolution
- Postmortem lessons accumulate over time
- Telegram alerts arrive for trades, errors, and daily summaries
- Web dashboard accessible from any browser via droplet IP
