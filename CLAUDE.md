# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Autonomous Polymarket trading bot: scans markets → researches via multi-source sentiment → predicts with XGBoost + Claude calibration → sizes with Kelly criterion → executes trades. Two dashboard frontends (Textual TUI, FastAPI web).

## Commands

```bash
# Install (editable + dev deps)
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Run single test file
python -m pytest tests/test_pipeline.py -v

# Run single test
python -m pytest tests/test_pipeline.py::test_function_name -v

# Main entry points
python run.py                          # Single dry-run cycle
python run.py --loop --interval=3600   # Continuous trading loop
python run.py --live                   # Real money (needs POLYMARKET_PRIVATE_KEY)
python run.py --web --host=0.0.0.0    # FastAPI web dashboard (port 8050)
python run.py --dashboard              # Textual terminal UI
python run.py --train                  # Train XGBoost model
python run.py --settle                 # Settlement monitor daemon
```

## Architecture

**Pipeline flow** (`run.py` → `src/pipeline.py`):
```
Scanner → ResearchPipeline → Predictor (XGBoost + Claude calibrator) → RiskManager (Kelly) → Executor (CLOB) → Postmortem
```

**Key design decisions:**
- Full async/await throughout; tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- SQLite with WAL mode and `threading.local()` for per-thread connections (`src/db.py`)
- Pydantic Settings for config validation from `.env` (`src/config.py`)
- Research sources are pluggable via `ResearchSource` ABC (`src/research/base.py`) and `StructuredDataSource` ABC (`src/research/structured_base.py`)
- Two-layer sentiment: VADER (fast) + Claude Haiku fallback for ambiguous texts (`src/research/sentiment.py`)
- `DashboardService` (`src/dashboard/service.py`) is a shared API layer consumed by both the Textual TUI and FastAPI web app
- Graceful degradation: research sources are optional; Google News RSS always works without auth

**Database:** SQLite at `data/polymarket.db` with 11 tables. Key tables: `scanned_markets`, `trades`, `predictions`, `postmortems`, `lessons`, `pnl_snapshots`.

## Deployment

Three systemd services on DigitalOcean (`deploy/`): trading loop, web dashboard, settlement monitor. Setup script: `deploy/setup.sh`.
