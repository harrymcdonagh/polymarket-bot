# Crypto 5-Minute Trading Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone crypto bot at `crypto/` inside the polymarket-bot repo that trades Polymarket's 5-minute crypto resolution markets using pandas-ta technical indicators (zero Claude API calls). Shares the same SQLite database for dashboard integration, but has its own bankroll, risk limits, settler, and process.

**Architecture:** Standalone `crypto/` subdirectory within `D:\polymarket-bot` (server: `/opt/polymarket-bot/crypto/`). Own entry point (`crypto/run.py`), own config, own risk manager, own settler. Shares SQLite DB file at `data/polymarket.db`. Dashboard integration via `/crypto` routes in existing web app.

**Tech Stack:** pandas-ta (indicators), ccxt (Coinbase 1m candles), py-clob-client (Polymarket orders), SQLite (shared DB), FastAPI (dashboard)

**Spec:** `docs/superpowers/specs/2026-03-17-crypto-5min-module-design.md`

---

## Separation of Concerns

| Concern | crypto/ (NEW) | Root polymarket-bot (EXISTING) |
|---------|---------------|-------------------------------|
| Entry point | `crypto/run.py --bot`, `--settle`, `--backtest` | `run.py --loop`, `--settle`, `--web` |
| Config | Own `crypto/.env`, own Settings class | Unchanged |
| Bankroll | `CRYPTO_BANKROLL` (separate) | `BANKROLL` (unchanged) |
| Daily loss limit | `CRYPTO_MAX_DAILY_LOSS` (separate) | `MAX_DAILY_LOSS` (unchanged) |
| Risk manager | Own CryptoRiskManager (simpler, no Kelly) | Unchanged |
| Settler | Own settler process (runs every 5 min) | Unchanged (runs every 1-2 hours) |
| Database | Creates 5 `crypto_*` tables in shared `data/polymarket.db` | Reads `crypto_*` tables for dashboard |
| Dashboard | None — no web server | Adds `/crypto` route + API endpoints |
| Systemd | `polymarket-crypto-bot.service`, `polymarket-crypto-settler.service` | Unchanged |

## Directory Structure

```
D:\polymarket-bot/                       # Existing repo root
├── run.py                               # Existing event bot entry point
├── pyproject.toml                       # Existing deps (unchanged)
├── src/                                 # Existing event bot code
├── tests/                               # Existing event bot tests
├── data/
│   └── polymarket.db                    # Shared SQLite DB
├── crypto/                              # NEW — standalone crypto bot
│   ├── run.py                           # Crypto entry: --bot, --settle, --backtest
│   ├── pyproject.toml                   # Own deps: pandas-ta, ccxt, py-clob-client
│   ├── .env.example                     # Template for crypto config
│   ├── src/
│   │   ├── __init__.py
│   │   ├── config.py                    # CryptoSettings (Pydantic, own .env)
│   │   ├── db.py                        # Database (creates crypto tables in shared DB)
│   │   ├── data_feed.py                 # 1m candles from Coinbase via ccxt
│   │   ├── indicators.py                # pandas-ta indicator computation
│   │   ├── scanner.py                   # Find active 5-min markets on Polymarket
│   │   ├── risk.py                      # CryptoRiskManager
│   │   ├── bot.py                       # Live trading loop (60s)
│   │   ├── settler.py                   # Crypto settler (5-min cycle)
│   │   ├── tracker.py                   # Incubation tracking
│   │   ├── strategies/
│   │   │   ├── __init__.py              # Strategy registry
│   │   │   ├── base.py                  # CryptoStrategy ABC
│   │   │   ├── macd_hist.py
│   │   │   ├── rsi_bb.py
│   │   │   ├── vwap_cap.py
│   │   │   └── ema_cross.py
│   │   └── backtester/
│   │       ├── __init__.py
│   │       ├── engine.py
│   │       └── runner.py
│   └── tests/
│       ├── test_config.py
│       ├── test_db.py
│       ├── test_data_feed.py
│       ├── test_indicators.py
│       ├── test_strategies.py
│       ├── test_backtest.py
│       ├── test_scanner.py
│       ├── test_risk.py
│       ├── test_bot.py
│       ├── test_settler.py
│       └── test_tracker.py
└── deploy/
    ├── polymarket-bot.service           # Existing
    ├── polymarket-web.service           # Existing
    ├── polymarket-settler.service       # Existing
    ├── polymarket-crypto-bot.service    # NEW
    └── polymarket-crypto-settler.service # NEW
```

## Files Modified in polymarket-bot (dashboard integration only)

| File | Change |
|------|--------|
| `src/db.py` | Add crypto read methods (gracefully handle missing tables): `get_crypto_trade_stats()`, `get_recent_crypto_trades()`, `get_crypto_pnl_history()`, `get_crypto_strategy_stats()`, `get_all_incubations()`, `get_top_crypto_backtests()` |
| `src/dashboard/web.py` | Add `/crypto` route + 6 `/api/crypto/*` endpoints |
| `src/dashboard/templates/index.html` | Add nav link to /crypto |
| `src/dashboard/templates/mobile.html` | Add nav link to /crypto |
| `src/dashboard/templates/crypto.html` | New crypto dashboard page |

---

## Phase 1: Project Setup + Data + Backtesting (polymarket-crypto-bot)

### Task 1: Project Scaffold + Config

**Files:**
- Create: `crypto/pyproject.toml`
- Create: `crypto/src\__init__.py`
- Create: `crypto/src\config.py`
- Create: `crypto/.env.example`
- Test: `crypto/tests\test_config.py`

- [ ] **Step 1: Create project directory and pyproject.toml**

```toml
[project]
name = "polymarket-crypto-bot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pandas-ta>=0.3.14b1",
    "ccxt>=4.2.0",
    "py-clob-client>=0.34.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
    "numpy>=1.26.0",
    "pandas>=2.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.14.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create .env.example**

```
# Polymarket
POLYMARKET_PRIVATE_KEY=
POLYMARKET_FUNDER_ADDRESS=
POLYMARKET_CLOB_URL=https://clob.polymarket.com
POLYMARKET_GAMMA_URL=https://gamma-api.polymarket.com

# Database (shared with event bot)
DB_PATH=../data/polymarket.db

# Crypto bot settings
CRYPTO_BANKROLL=100.0
CRYPTO_MAX_DAILY_LOSS=20.0
CRYPTO_POSITION_SIZE=1.50
CRYPTO_MAX_POSITION_SIZE=100.0
CRYPTO_STRATEGY=macd_hist
CRYPTO_STRATEGY_PARAMS={"macd_fast":3,"macd_slow":15,"macd_signal":3}
CRYPTO_SYMBOL=BTC
CRYPTO_CANDLE_WINDOW=100
CRYPTO_INCUBATION_MIN_DAYS=14
CRYPTO_SCALE_SEQUENCE=1.50,5,10,25,50,100
CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS=3
POLYMARKET_FEE=0.02

# Logging
LOG_LEVEL=INFO
```

- [ ] **Step 3: Write config tests**

```python
# tests/test_config.py
import pytest
from src.config import Settings


def test_defaults():
    s = Settings(DB_PATH="data/test.db")
    assert s.CRYPTO_BANKROLL == 100.0
    assert s.CRYPTO_MAX_DAILY_LOSS == 20.0
    assert s.CRYPTO_POSITION_SIZE == 1.50
    assert s.CRYPTO_MAX_POSITION_SIZE == 100.0
    assert s.CRYPTO_STRATEGY == "macd_hist"
    assert s.CRYPTO_SYMBOL == "BTC"
    assert s.CRYPTO_CANDLE_WINDOW == 100
    assert s.CRYPTO_INCUBATION_MIN_DAYS == 14
    assert s.CRYPTO_SCALE_SEQUENCE == "1.50,5,10,25,50,100"
    assert s.CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS == 3
    assert s.POLYMARKET_FEE == 0.02


def test_strategy_params_valid():
    s = Settings(
        DB_PATH="data/test.db",
        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}',
    )
    assert s.CRYPTO_STRATEGY_PARAMS == '{"macd_fast":3,"macd_slow":15,"macd_signal":3}'


def test_strategy_params_invalid_json():
    with pytest.raises(Exception):
        Settings(DB_PATH="data/test.db", CRYPTO_STRATEGY_PARAMS="not json")


def test_position_size_positive():
    with pytest.raises(Exception):
        Settings(DB_PATH="data/test.db", CRYPTO_POSITION_SIZE=-1.0)


def test_bankroll_positive():
    with pytest.raises(Exception):
        Settings(DB_PATH="data/test.db", CRYPTO_BANKROLL=0)
```

- [ ] **Step 4: Implement Settings class**

```python
# src/config.py
import json
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Polymarket
    POLYMARKET_PRIVATE_KEY: str = ""
    POLYMARKET_FUNDER_ADDRESS: str = ""
    POLYMARKET_CLOB_URL: str = "https://clob.polymarket.com"
    POLYMARKET_GAMMA_URL: str = "https://gamma-api.polymarket.com"

    # Database (shared with event bot)
    DB_PATH: str = "../data/polymarket.db"

    # Crypto bot settings
    CRYPTO_BANKROLL: float = 100.0
    CRYPTO_MAX_DAILY_LOSS: float = 20.0
    CRYPTO_POSITION_SIZE: float = 1.50
    CRYPTO_MAX_POSITION_SIZE: float = 100.0
    CRYPTO_STRATEGY: str = "macd_hist"
    CRYPTO_STRATEGY_PARAMS: str = '{"macd_fast":3,"macd_slow":15,"macd_signal":3}'
    CRYPTO_SYMBOL: str = "BTC"
    CRYPTO_CANDLE_WINDOW: int = 100
    CRYPTO_INCUBATION_MIN_DAYS: int = 14
    CRYPTO_SCALE_SEQUENCE: str = "1.50,5,10,25,50,100"
    CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS: int = 3
    POLYMARKET_FEE: float = 0.02

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator("CRYPTO_STRATEGY_PARAMS")
    @classmethod
    def valid_strategy_params(cls, v: str) -> str:
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError("CRYPTO_STRATEGY_PARAMS must be valid JSON")
        return v

    @field_validator("CRYPTO_POSITION_SIZE")
    @classmethod
    def position_size_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("CRYPTO_POSITION_SIZE must be positive")
        return v

    @field_validator("CRYPTO_BANKROLL")
    @classmethod
    def bankroll_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("CRYPTO_BANKROLL must be positive")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def valid_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return v.upper()
```

- [ ] **Step 5: Create src/__init__.py (empty)**

- [ ] **Step 6: Install and run tests**

```bash
cd D:\polymarket-bot\crypto
pip install -e ".[dev]"
python -m pytest tests/test_config.py -v
```

- [ ] **Step 7: Commit**

```bash
cd D:\polymarket-bot
git add crypto/pyproject.toml crypto/src/ crypto/tests/ crypto/.env.example
git commit -m "feat(crypto): project scaffold with config and settings"
```

---

### Task 2: Database — 5 Crypto Tables

**Files:**
- Create: `crypto/src\db.py`
- Test: `crypto/tests\test_db.py`

- [ ] **Step 1: Write DB tests**

```python
# tests/test_db.py
import pytest
from src.db import Database


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    d.init()
    return d


def test_crypto_tables_created(db):
    conn = db._conn()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "crypto_candles" in tables
    assert "crypto_backtests" in tables
    assert "crypto_trades" in tables
    assert "crypto_incubation" in tables
    assert "crypto_pnl_daily" in tables


def test_save_and_get_crypto_trade(db):
    db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt123",
        side="YES", entry_price=0.52, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=1.50,
        status="dry_run_open", signal_data='{"macd_hist": 0.5}',
        token_id="tok123",
    )
    trades = db.get_open_crypto_trades()
    assert len(trades) == 1
    assert trades[0]["strategy"] == "macd_hist"
    assert trades[0]["token_id"] == "tok123"


def test_settle_crypto_trade(db):
    db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt1",
        side="YES", entry_price=0.50, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=1.50,
        status="dry_run_open", signal_data="{}",
    )
    trades = db.get_open_crypto_trades()
    updated = db.settle_crypto_trade(trades[0]["id"], status="dry_run_won", pnl=1.47)
    assert updated is True
    settled = db.get_settled_crypto_trades(limit=10)
    assert len(settled) == 1
    assert settled[0]["pnl"] == 1.47


def test_settle_with_expected_status_guard(db):
    db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt1",
        side="YES", entry_price=0.50, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=1.50,
        status="dry_run_open", signal_data="{}",
    )
    trades = db.get_open_crypto_trades()
    tid = trades[0]["id"]
    # First settle succeeds
    assert db.settle_crypto_trade(tid, "dry_run_won", 1.47, expected_status="dry_run_open") is True
    # Second settle with wrong expected_status fails silently (race guard)
    assert db.settle_crypto_trade(tid, "dry_run_lost", -1.53, expected_status="dry_run_open") is False


def test_get_crypto_daily_pnl(db):
    pnl = db.get_crypto_daily_pnl()
    assert pnl == 0.0


def test_save_and_get_candles(db):
    candles = [
        {"symbol": "BTC", "timestamp": "2026-03-18T12:00:00",
         "open": 84000, "high": 84100, "low": 83900, "close": 84050, "volume": 100},
        {"symbol": "BTC", "timestamp": "2026-03-18T12:01:00",
         "open": 84050, "high": 84150, "low": 83950, "close": 84100, "volume": 120},
    ]
    db.save_crypto_candles(candles)
    result = db.get_crypto_candles("BTC", limit=10)
    assert len(result) == 2


def test_save_and_get_backtest(db):
    db.save_crypto_backtest(
        strategy="macd_hist",
        params='{"macd_fast":3,"macd_slow":15,"macd_signal":3}',
        symbol="BTC", total_trades=100, win_rate=0.55,
        expectancy=0.03, total_pnl=45.0, max_drawdown=-12.0,
        profit_factor=1.2, sharpe=1.5,
    )
    results = db.get_top_crypto_backtests(limit=5)
    assert len(results) == 1
    assert results[0]["strategy"] == "macd_hist"


def test_upsert_crypto_pnl_daily(db):
    db.upsert_crypto_pnl_daily(
        date="2026-03-18", trades_count=5, wins=3, losses=2,
        gross_pnl=3.0, fees=0.15, net_pnl=2.85, bankroll=97.85,
    )
    rows = db.get_crypto_pnl_history()
    assert len(rows) == 1
    assert rows[0]["net_pnl"] == 2.85


def test_get_or_create_incubation(db):
    inc = db.get_or_create_incubation("macd_hist")
    assert inc["strategy"] == "macd_hist"
    assert inc["position_size"] == 1.50
    inc2 = db.get_or_create_incubation("macd_hist")
    assert inc2["id"] == inc["id"]


def test_get_crypto_trade_stats(db):
    stats = db.get_crypto_trade_stats()
    assert stats["total_trades"] == 0
    assert stats["win_rate"] == 0.0


def test_get_crypto_strategy_stats(db):
    stats = db.get_crypto_strategy_stats()
    assert stats == []
```

- [ ] **Step 2: Implement Database class**

Create `src/db.py` with:
- 5 crypto tables (crypto_candles, crypto_backtests, crypto_trades with token_id column, crypto_incubation with UNIQUE strategy, crypto_pnl_daily)
- Methods: `save_crypto_trade`, `get_open_crypto_trades`, `settle_crypto_trade` (with `expected_status` guard), `get_settled_crypto_trades`, `get_recent_crypto_trades`, `get_crypto_daily_pnl`, `save_crypto_candles`, `get_crypto_candles`, `save_crypto_backtest`, `get_top_crypto_backtests`, `upsert_crypto_pnl_daily` (with bankroll_after), `get_crypto_pnl_history`, `get_or_create_incubation`, `update_incubation`, `get_crypto_trade_stats`, `get_crypto_strategy_stats`, `get_all_incubations`
- Same SQLite pattern as polymarket-bot: WAL mode, threading.local(), busy_timeout=30000

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_db.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/db.py tests/test_db.py
git commit -m "feat: add database with 5 crypto tables and query methods"
```

---

### Task 3: Data Feed (ccxt)

**Files:**
- Create: `src/data_feed.py`
- Test: `tests/test_data_feed.py`

- [ ] **Step 1: Write tests**

Test CryptoDataFeed: returns DataFrame with correct columns, returns None on insufficient data or errors. Mock ccxt exchange.

- [ ] **Step 2: Implement CryptoDataFeed**

Fetches 1m candles from Coinbase via ccxt async. Returns pd.DataFrame or None. Has min_candles threshold (default 60).

- [ ] **Step 3: Run tests, commit**

---

### Task 4: Indicators (pandas-ta)

**Files:**
- Create: `src/indicators.py`
- Test: `tests/test_indicators.py`

- [ ] **Step 1: Write tests**

Test `compute_indicators()` adds all expected columns (macd, macd_signal, macd_hist, rsi, bb_upper/mid/lower/bandwidth, vwap, ema_fast/slow, vol_sma, vol_spike_ratio, atr). Test custom params. Test with insufficient data (no crash, NaN values).

- [ ] **Step 2: Implement compute_indicators()**

All pandas-ta indicators with configurable params.

- [ ] **Step 3: Run tests, commit**

---

### Task 5: Strategy Base Class + MACD Histogram

**Files:**
- Create: `src/strategies/__init__.py`, `src/strategies/base.py`, `src/strategies/macd_hist.py`
- Test: `tests/test_strategies.py`

- [ ] **Step 1: Write tests** for CryptoStrategy ABC and MACDHistStrategy

- [ ] **Step 2: Implement** base class (ABC with generate_signal, backtest_signal, params_dict) and MACD histogram strategy

- [ ] **Step 3: Create `__init__.py`** with only macd_hist in STRATEGY_REGISTRY

- [ ] **Step 4: Run tests, commit**

---

### Task 6: Remaining 3 Strategies

**Files:**
- Create: `src/strategies/rsi_bb.py`, `src/strategies/vwap_cap.py`, `src/strategies/ema_cross.py`
- Modify: `src/strategies/__init__.py`
- Test: extend `tests/test_strategies.py`

- [ ] **Step 1: Add tests** for RSIBBStrategy, VWAPCapStrategy, EMACrossStrategy

- [ ] **Step 2: Implement** all three strategies

- [ ] **Step 3: Update registry** with all 4 strategies

- [ ] **Step 4: Run tests, commit**

---

### Task 7: Backtest Engine + Runner

**Files:**
- Create: `src/backtester/__init__.py`, `src/backtester/engine.py`, `src/backtester/runner.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write tests** for BacktestEngine (P&L math, run method, no-trade case) and BacktestRunner (grid sweep, DB saves)

- [ ] **Step 2: Implement** BacktestEngine (simulates 5-min binary markets, uses POLYMARKET_FEE from config) and BacktestRunner (PARAM_GRID, sequential execution, saves to DB)

- [ ] **Step 3: Run tests, commit**

---

## Phase 2: Live Bot (polymarket-crypto-bot)

### Task 8: Risk Manager

**Files:**
- Create: `src/risk.py`
- Test: `tests/test_risk.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_risk.py
from src.risk import CryptoRiskManager


def test_approved():
    rm = CryptoRiskManager(max_daily_loss=20.0, max_position_size=100.0)
    ok, reason = rm.check(daily_pnl=0.0, proposed_size=1.50, has_open_trade=False)
    assert ok is True


def test_daily_loss_exceeded():
    rm = CryptoRiskManager(max_daily_loss=20.0, max_position_size=100.0)
    ok, reason = rm.check(daily_pnl=-21.0, proposed_size=1.50, has_open_trade=False)
    assert ok is False
    assert "daily loss" in reason.lower()


def test_has_open_trade():
    rm = CryptoRiskManager(max_daily_loss=20.0, max_position_size=100.0)
    ok, reason = rm.check(daily_pnl=0.0, proposed_size=1.50, has_open_trade=True)
    assert ok is False


def test_size_too_large():
    rm = CryptoRiskManager(max_daily_loss=20.0, max_position_size=100.0)
    ok, reason = rm.check(daily_pnl=0.0, proposed_size=200.0, has_open_trade=False)
    assert ok is False
```

- [ ] **Step 2: Implement CryptoRiskManager**

Simple standalone class (no dependency on polymarket-bot's RiskManager):
- `check(daily_pnl, proposed_size, has_open_trade) -> (bool, str)`
- Checks: daily loss limit, max position size, no concurrent trades

- [ ] **Step 3: Run tests, commit**

---

### Task 9: Market Scanner

**Files:**
- Create: `src/scanner.py`
- Test: `tests/test_scanner.py`

- [ ] **Step 1: Write tests** — mock Gamma API, test find_active_5min_market() returns dict or None, test check_resolution() using clob_token_ids

- [ ] **Step 2: Implement CryptoScanner** with 60s cache, check_resolution using clob_token_ids (not condition_id — Gamma API ignores it)

- [ ] **Step 3: Run tests, commit**

---

### Task 10: Incubation Tracker

**Files:**
- Create: `src/tracker.py`
- Test: `tests/test_tracker.py`

- [ ] **Step 1: Write tests** — update_after_trade, get_current_size, check_scale_up, check_retire

- [ ] **Step 2: Implement IncubationTracker** with scale sequence [1.50, 5, 10, 25, 50, 100], min 14 days, max consecutive loss days

- [ ] **Step 3: Run tests, commit**

---

### Task 11: Live Bot

**Files:**
- Create: `src/bot.py`
- Test: `tests/test_bot.py`

- [ ] **Step 1: Write tests**

Test: is_5min_boundary(), calc_crypto_pnl(), bot initializes strategy, cycle with no signal, cycle not at boundary.

- [ ] **Step 2: Implement CryptoBot**

60s main loop:
1. Settle open trades inline
2. If at 5-min boundary: fetch candles → compute indicators → generate signal
3. If signal: risk check → find market → place order (or dry-run) → save to DB
4. Stop after 5 consecutive errors

Order placement: uses py-clob-client directly (limit orders). Dry-run mode saves as `dry_run_open`.

- [ ] **Step 3: Run tests, commit**

---

### Task 12: Settler

**Files:**
- Create: `src/settler.py`
- Test: `tests/test_settler.py`

- [ ] **Step 1: Write tests** — settle open trades, race condition guard (expected_status), PnL calculation

- [ ] **Step 2: Implement CryptoSettler**

Runs every 5 minutes (much more frequent than event settler). Checks open crypto trades, resolves via Gamma API using clob_token_ids, settles with expected_status guard, updates crypto_pnl_daily and incubation tracker.

- [ ] **Step 3: Run tests, commit**

---

### Task 13: Entry Point (run.py)

**Files:**
- Create: `crypto/run.py`

- [ ] **Step 1: Implement run.py**

```python
# Modes:
# python run.py --bot              # Dry-run crypto bot
# python run.py --bot --live       # Live crypto bot
# python run.py --settle           # Settler daemon (every 5 min)
# python run.py --backtest         # Run full backtest grid
```

Mutual exclusion: `--bot`, `--settle`, `--backtest` are exclusive.

- [ ] **Step 2: Commit**

---

### Task 14: Deployment

**Files:**
- Create: `deploy/setup.sh`
- Create: `deploy/polymarket-crypto-bot.service`
- Create: `deploy/polymarket-crypto-settler.service`

- [ ] **Step 1: Create systemd services**

Bot service: runs `python run.py --bot` (or `--bot --live`), WorkingDirectory=/opt/polymarket-bot/crypto
Settler service: runs `python run.py --settle`, WorkingDirectory=/opt/polymarket-bot/crypto, RestartSec=10

Both use a separate venv at `/opt/polymarket-bot/crypto/venv` (different deps from event bot).

- [ ] **Step 2: Create setup.sh**

Creates venv at `/opt/polymarket-bot/crypto/venv`, installs deps, creates .env pointing DB_PATH to `/opt/polymarket-bot/data/polymarket.db`, installs systemd services.

- [ ] **Step 3: Commit**

---

## Phase 3: Dashboard Integration (polymarket-bot)

### Task 15: Dashboard Read Methods in polymarket-bot

**Files:**
- Modify: `D:\polymarket-bot\src\db.py`
- Test: `D:\polymarket-bot\tests\test_crypto_db.py`

- [ ] **Step 1: Write tests** in polymarket-bot for read-only crypto methods

Test: `get_crypto_trade_stats()`, `get_recent_crypto_trades()`, `get_crypto_pnl_history()`, `get_crypto_strategy_stats()`, `get_all_incubations()`, `get_top_crypto_backtests()`. These read from tables created by the crypto bot.

- [ ] **Step 2: Add read methods** to polymarket-bot's `src/db.py`

These are read-only — the crypto bot writes, the dashboard reads. The methods must handle the case where crypto tables don't exist yet (return empty results, don't crash).

- [ ] **Step 3: Run all polymarket-bot tests for regressions**

```bash
cd D:\polymarket-bot
python -m pytest tests/ -v
```

- [ ] **Step 4: Commit in polymarket-bot**

---

### Task 16: Dashboard API Endpoints

**Files:**
- Modify: `D:\polymarket-bot\src\dashboard\web.py`

- [ ] **Step 1: Add crypto routes**

```
GET /crypto          → serves crypto.html template
GET /api/crypto/stats     → today PnL, win rate, total trades, bankroll, bot status
GET /api/crypto/trades    → recent crypto trades (paginated)
GET /api/crypto/pnl-history → daily PnL series
GET /api/crypto/strategies  → per-strategy stats
GET /api/crypto/incubation  → incubation status table
GET /api/crypto/backtests   → top 5 backtest configs
```

- [ ] **Step 2: Run web tests**

- [ ] **Step 3: Commit in polymarket-bot**

---

### Task 17: Dashboard Template + Navigation

**Files:**
- Modify: `D:\polymarket-bot\src\dashboard\templates\index.html`
- Modify: `D:\polymarket-bot\src\dashboard\templates\mobile.html`
- Create: `D:\polymarket-bot\src\dashboard\templates\crypto.html`

- [ ] **Step 1: Add nav bar** to existing templates (link to /crypto)

- [ ] **Step 2: Create crypto.html** — stats bar (5 cards), cumulative P&L chart, trades table, strategy comparison, incubation status, backtest results. Same dark theme and HTMX patterns as existing dashboard.

- [ ] **Step 3: Commit in polymarket-bot**

---

### Task 18: Full Integration Test

- [ ] **Step 1: Run full crypto test suite**

```bash
cd D:\polymarket-bot\crypto
python -m pytest tests/ -v
```

- [ ] **Step 2: Run full event bot test suite**

```bash
cd D:\polymarket-bot
python -m pytest tests/ -v
```

- [ ] **Step 3: Verify CLI modes work**

```bash
cd D:\polymarket-bot\crypto
python -c "from src.bot import CryptoBot; print('import ok')"
python -c "from src.strategies import STRATEGY_REGISTRY; print(list(STRATEGY_REGISTRY.keys()))"
```

- [ ] **Step 4: Final commit**
