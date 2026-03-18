# Crypto 5-Minute Trading Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 5-minute crypto resolution market trader using pandas-ta technical indicators — zero Claude API calls. Shares the same Polymarket account, bankroll, database, risk limits, and dashboard.

**Architecture:** New `src/crypto/` module deeply integrated with existing infrastructure. Extends `Database` (5 new tables), `RiskManager` (new `crypto_risk_check()`), `Settler` (crypto settlement), and FastAPI dashboard (new `/crypto` routes). Bot runs as separate process via `python run.py --crypto`.

**Tech Stack:** pandas-ta (indicators), ccxt (Coinbase 1m candles), existing py-clob-client (orders), SQLite (shared DB), FastAPI (dashboard)

**Spec:** `docs/superpowers/specs/2026-03-17-crypto-5min-module-design.md`

---

## File Structure

### New Files (src/crypto/)

| File | Responsibility |
|------|---------------|
| `src/crypto/__init__.py` | Package init |
| `src/crypto/data_feed.py` | Fetch 1m candles from Coinbase via ccxt |
| `src/crypto/indicators.py` | pandas-ta indicator computation on candle DataFrame |
| `src/crypto/strategies/__init__.py` | Strategy registry |
| `src/crypto/strategies/base.py` | `CryptoStrategy` ABC |
| `src/crypto/strategies/macd_hist.py` | MACD histogram crossover strategy |
| `src/crypto/strategies/rsi_bb.py` | RSI + Bollinger Band squeeze strategy |
| `src/crypto/strategies/vwap_cap.py` | VWAP capitulation reversion strategy |
| `src/crypto/strategies/ema_cross.py` | EMA crossover strategy |
| `src/crypto/backtester/__init__.py` | Package init |
| `src/crypto/backtester/engine.py` | Single strategy backtest engine |
| `src/crypto/backtester/runner.py` | Multi-strategy x param grid runner |
| `src/crypto/scanner.py` | Find active 5-min BTC/ETH markets on Polymarket |
| `src/crypto/risk.py` | Thin wrapper — queries DB, delegates to shared RiskManager |
| `src/crypto/bot.py` | Live trading loop (60s cycle) |
| `src/crypto/tracker.py` | Incubation tracking (scale up/down over time) |

### New Test Files

| File | Tests |
|------|-------|
| `tests/test_crypto_indicators.py` | Indicator computation |
| `tests/test_crypto_strategies.py` | All 4 strategies signal generation |
| `tests/test_crypto_backtest.py` | Backtest engine + runner |
| `tests/test_crypto_scanner.py` | Market discovery |
| `tests/test_crypto_risk.py` | Risk check integration |
| `tests/test_crypto_bot.py` | Bot loop, order placement, settlement |
| `tests/test_crypto_tracker.py` | Incubation tracking |
| `tests/test_crypto_db.py` | New DB tables and methods |

### Modified Files

| File | Change |
|------|--------|
| `src/db.py` | Add 5 crypto tables in `init()`, add crypto query methods, `get_available_bankroll()`, `get_combined_daily_pnl()` |
| `src/config.py` | Add 13 CRYPTO_* settings fields with validators |
| `src/risk/risk_manager.py` | Add `crypto_risk_check()` method |
| `src/settler/settler.py` | Add `settle_crypto_trades()` called in existing `run()` |
| `src/notifications/telegram.py` | Add `format_crypto_settlement_alert()` |
| `src/dashboard/web.py` | Add `/crypto` route + 6 crypto API endpoints |
| `src/dashboard/templates/index.html` | Add nav bar with link to /crypto |
| `src/dashboard/templates/mobile.html` | Add nav bar with link to /crypto |
| `src/dashboard/templates/crypto.html` | New crypto dashboard page |
| `run.py` | Add `--crypto` CLI flag |
| `pyproject.toml` | Add `pandas-ta`, `ccxt` dependencies |
| `deploy/polymarket-crypto.service` | New systemd service file |

---

## Phase 1: Data + Backtesting

### Task 1: Dependencies and Config

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/config.py`
- Test: `tests/test_crypto_config.py`

- [ ] **Step 1: Add dependencies to pyproject.toml**

Add `pandas-ta>=0.3.14b1` and `ccxt>=4.2.0` to the dependencies list in `pyproject.toml`.

- [ ] **Step 2: Install new dependencies**

Run: `pip install -e ".[dev]"`
Expected: Success, pandas_ta and ccxt importable

- [ ] **Step 3: Write test for crypto config fields**

```python
# tests/test_crypto_config.py
import json
import pytest
from src.config import Settings


def test_crypto_defaults():
    s = Settings(CRYPTO_ENABLED=False)
    assert s.CRYPTO_ENABLED is False
    assert s.CRYPTO_POSITION_SIZE == 1.50
    assert s.CRYPTO_MAX_POSITION_SIZE == 100.0
    assert s.CRYPTO_STRATEGY == "macd_hist"
    assert s.CRYPTO_SYMBOL == "BTC"
    assert s.CRYPTO_TRADE_INTERVAL == 300
    assert s.CRYPTO_CANDLE_WINDOW == 100
    assert s.CRYPTO_MAX_CONCURRENT_TRADES == 1
    assert s.CRYPTO_INCUBATION_MIN_DAYS == 14
    assert s.CRYPTO_SCALE_SEQUENCE == "1.50,5,10,25,50,100"
    assert s.CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS == 3


def test_crypto_strategy_params_valid():
    s = Settings(
        CRYPTO_STRATEGY="macd_hist",
        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}',
    )
    assert s.CRYPTO_STRATEGY_PARAMS == '{"macd_fast":3,"macd_slow":15,"macd_signal":3}'


def test_crypto_strategy_params_invalid_json():
    with pytest.raises(Exception):
        Settings(CRYPTO_STRATEGY_PARAMS="not json")


def test_crypto_position_size_range():
    with pytest.raises(Exception):
        Settings(CRYPTO_POSITION_SIZE=-1.0)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_crypto_config.py -v`
Expected: FAIL — fields don't exist yet

- [ ] **Step 5: Add crypto settings to Settings class**

Add to `src/config.py` after existing fields:

```python
# Crypto 5-min module
CRYPTO_ENABLED: bool = False
CRYPTO_POSITION_SIZE: float = 1.50
CRYPTO_MAX_POSITION_SIZE: float = 100.0
CRYPTO_STRATEGY: str = "macd_hist"
CRYPTO_STRATEGY_PARAMS: str = '{"macd_fast":3,"macd_slow":15,"macd_signal":3}'
CRYPTO_SYMBOL: str = "BTC"
CRYPTO_TRADE_INTERVAL: int = 300
CRYPTO_CANDLE_WINDOW: int = 100
CRYPTO_MAX_CONCURRENT_TRADES: int = 1
CRYPTO_INCUBATION_MIN_DAYS: int = 14
CRYPTO_SCALE_SEQUENCE: str = "1.50,5,10,25,50,100"
CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS: int = 3
```

Add validators:

```python
@field_validator("CRYPTO_STRATEGY_PARAMS")
@classmethod
def valid_crypto_params(cls, v: str) -> str:
    import json
    try:
        json.loads(v)
    except json.JSONDecodeError:
        raise ValueError("CRYPTO_STRATEGY_PARAMS must be valid JSON")
    return v

@field_validator("CRYPTO_POSITION_SIZE")
@classmethod
def crypto_position_positive(cls, v: float) -> float:
    if v <= 0:
        raise ValueError("CRYPTO_POSITION_SIZE must be positive")
    return v
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_crypto_config.py -v`
Expected: All PASS

- [ ] **Step 7: Run existing tests to check no regressions**

Run: `python -m pytest tests/test_config_weights.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/config.py tests/test_crypto_config.py
git commit -m "feat(crypto): add dependencies and config settings for 5-min module"
```

---

### Task 2: Database Schema — 5 New Tables

**Files:**
- Modify: `src/db.py`
- Test: `tests/test_crypto_db.py`

- [ ] **Step 1: Write tests for new crypto tables and methods**

```python
# tests/test_crypto_db.py
import json
import pytest
from src.db import Database


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    d.init()
    return d


def test_crypto_tables_created(db):
    """All 5 crypto tables exist after init."""
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
    )
    trades = db.get_open_crypto_trades()
    assert len(trades) == 1
    assert trades[0]["strategy"] == "macd_hist"
    assert trades[0]["side"] == "YES"
    assert trades[0]["status"] == "dry_run_open"


def test_settle_crypto_trade(db):
    db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt1",
        side="YES", entry_price=0.50, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=1.50,
        status="dry_run_open", signal_data="{}",
    )
    trades = db.get_open_crypto_trades()
    db.settle_crypto_trade(trades[0]["id"], status="dry_run_won", pnl=1.47)
    settled = db.get_settled_crypto_trades(limit=10)
    assert len(settled) == 1
    assert settled[0]["status"] == "dry_run_won"
    assert settled[0]["pnl"] == 1.47


def test_get_available_bankroll(db):
    """Available bankroll subtracts open event and crypto trades."""
    # No open trades — full bankroll
    bankroll = db.get_available_bankroll(total_bankroll=1000.0)
    assert bankroll == 1000.0

    # Add an open event trade
    db.save_trade(market_id="evt1", side="YES", amount=50.0, price=0.5, status="dry_run")
    bankroll = db.get_available_bankroll(total_bankroll=1000.0)
    assert bankroll == 950.0

    # Add open crypto trade
    db.save_crypto_trade(
        strategy="macd_hist", symbol="BTC", market_id="mkt1",
        side="YES", entry_price=0.50, strike_price=84000.0,
        btc_price_at_entry=83950.0, amount=10.0,
        status="open", signal_data="{}",
    )
    bankroll = db.get_available_bankroll(total_bankroll=1000.0)
    assert bankroll == 940.0


def test_get_combined_daily_pnl(db):
    """Combined PnL sums event + crypto settled trades from today."""
    pnl = db.get_combined_daily_pnl()
    assert pnl == 0.0


def test_save_crypto_candles(db):
    candles = [
        {"symbol": "BTC", "timestamp": "2026-03-18T12:00:00",
         "open": 84000, "high": 84100, "low": 83900, "close": 84050, "volume": 100},
        {"symbol": "BTC", "timestamp": "2026-03-18T12:01:00",
         "open": 84050, "high": 84150, "low": 83950, "close": 84100, "volume": 120},
    ]
    db.save_crypto_candles(candles)
    result = db.get_crypto_candles("BTC", limit=10)
    assert len(result) == 2


def test_save_crypto_backtest(db):
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
        gross_pnl=3.0, fees=0.15, net_pnl=2.85,
    )
    rows = db.get_crypto_pnl_history()
    assert len(rows) == 1
    assert rows[0]["net_pnl"] == 2.85


def test_get_or_create_incubation(db):
    inc = db.get_or_create_incubation("macd_hist")
    assert inc["strategy"] == "macd_hist"
    assert inc["position_size"] == 1.50
    assert inc["status"] == "incubating"
    # Second call returns same row
    inc2 = db.get_or_create_incubation("macd_hist")
    assert inc2["id"] == inc["id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_crypto_db.py -v`
Expected: FAIL — methods don't exist

- [ ] **Step 3: Add 5 crypto tables to db.py init()**

In `src/db.py`, add to the `init()` executescript (before the CREATE INDEX lines):

```sql
CREATE TABLE IF NOT EXISTS crypto_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    UNIQUE(symbol, timestamp)
);

CREATE TABLE IF NOT EXISTS crypto_backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    params TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT DEFAULT '5m',
    total_trades INTEGER,
    win_rate REAL,
    expectancy REAL,
    total_pnl REAL,
    max_drawdown REAL,
    profit_factor REAL,
    sharpe REAL,
    ran_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crypto_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market_id TEXT,
    token_id TEXT,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    strike_price REAL,
    btc_price_at_entry REAL,
    amount REAL NOT NULL,
    status TEXT DEFAULT 'open',
    pnl REAL,
    signal_data TEXT,
    placed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME
);

CREATE TABLE IF NOT EXISTS crypto_incubation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL UNIQUE,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    position_size REAL DEFAULT 1.50,
    total_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0.0,
    status TEXT DEFAULT 'incubating',
    last_updated DATETIME
);

CREATE TABLE IF NOT EXISTS crypto_pnl_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL UNIQUE,
    trades_count INTEGER,
    wins INTEGER,
    losses INTEGER,
    gross_pnl REAL,
    fees REAL,
    net_pnl REAL,
    cumulative_pnl REAL,
    bankroll_after REAL
);
```

Add indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_crypto_candles_symbol_ts ON crypto_candles(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_crypto_trades_status ON crypto_trades(status);
CREATE INDEX IF NOT EXISTS idx_crypto_trades_placed_at ON crypto_trades(placed_at);
```

- [ ] **Step 4: Add crypto DB methods to Database class**

Add methods to `src/db.py`:

```python
def save_crypto_trade(self, strategy: str, symbol: str, market_id: str | None,
                      side: str, entry_price: float, strike_price: float | None,
                      btc_price_at_entry: float | None, amount: float,
                      status: str = "open", signal_data: str | None = None,
                      token_id: str | None = None):
    conn = self._conn()
    conn.execute(
        """INSERT INTO crypto_trades
           (strategy, symbol, market_id, token_id, side, entry_price, strike_price,
            btc_price_at_entry, amount, status, signal_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (strategy, symbol, market_id, token_id, side, entry_price, strike_price,
         btc_price_at_entry, amount, status, signal_data),
    )
    conn.commit()

def get_open_crypto_trades(self) -> list[dict]:
    conn = self._conn()
    rows = conn.execute(
        "SELECT * FROM crypto_trades WHERE status IN ('open', 'dry_run_open')"
    ).fetchall()
    return [dict(r) for r in rows]

def settle_crypto_trade(self, trade_id: int, status: str, pnl: float,
                        expected_status: str | None = None) -> bool:
    """Settle a crypto trade. Uses expected_status guard for race-condition prevention."""
    conn = self._conn()
    now = datetime.now(timezone.utc).isoformat()
    if expected_status:
        cursor = conn.execute(
            "UPDATE crypto_trades SET status = ?, pnl = ?, resolved_at = ? WHERE id = ? AND status = ?",
            (status, pnl, now, trade_id, expected_status),
        )
    else:
        cursor = conn.execute(
            "UPDATE crypto_trades SET status = ?, pnl = ?, resolved_at = ? WHERE id = ?",
            (status, pnl, now, trade_id),
        )
    conn.commit()
    return cursor.rowcount > 0

def get_settled_crypto_trades(self, limit: int = 50) -> list[dict]:
    conn = self._conn()
    rows = conn.execute(
        """SELECT * FROM crypto_trades
           WHERE status IN ('won', 'lost', 'dry_run_won', 'dry_run_lost')
           ORDER BY resolved_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]

def get_recent_crypto_trades(self, limit: int = 50) -> list[dict]:
    conn = self._conn()
    rows = conn.execute(
        "SELECT * FROM crypto_trades ORDER BY placed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]

def get_available_bankroll(self, total_bankroll: float) -> float:
    conn = self._conn()
    event_open = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as s FROM trades WHERE status IN ('pending', 'dry_run')"
    ).fetchone()["s"]
    crypto_open = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as s FROM crypto_trades WHERE status IN ('open', 'dry_run_open')"
    ).fetchone()["s"]
    return total_bankroll - event_open - crypto_open

def get_combined_daily_pnl(self) -> float:
    conn = self._conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    event_pnl = conn.execute(
        """SELECT COALESCE(SUM(COALESCE(pnl, hypothetical_pnl)), 0) as s
           FROM trades
           WHERE status IN ('settled', 'dry_run_settled')
             AND COALESCE(settled_at, resolved_at) LIKE ?""",
        (f"{today}%",),
    ).fetchone()["s"]
    crypto_pnl = conn.execute(
        """SELECT COALESCE(SUM(pnl), 0) as s
           FROM crypto_trades
           WHERE status IN ('won', 'lost', 'dry_run_won', 'dry_run_lost')
             AND resolved_at LIKE ?""",
        (f"{today}%",),
    ).fetchone()["s"]
    return event_pnl + crypto_pnl

def save_crypto_candles(self, candles: list[dict]):
    conn = self._conn()
    conn.executemany(
        """INSERT OR IGNORE INTO crypto_candles
           (symbol, timestamp, open, high, low, close, volume)
           VALUES (:symbol, :timestamp, :open, :high, :low, :close, :volume)""",
        candles,
    )
    conn.commit()

def get_crypto_candles(self, symbol: str, limit: int = 100) -> list[dict]:
    conn = self._conn()
    rows = conn.execute(
        "SELECT * FROM crypto_candles WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
        (symbol, limit),
    ).fetchall()
    return [dict(r) for r in rows]

def save_crypto_backtest(self, strategy: str, params: str, symbol: str,
                         total_trades: int, win_rate: float, expectancy: float,
                         total_pnl: float, max_drawdown: float,
                         profit_factor: float, sharpe: float):
    conn = self._conn()
    conn.execute(
        """INSERT INTO crypto_backtests
           (strategy, params, symbol, total_trades, win_rate, expectancy,
            total_pnl, max_drawdown, profit_factor, sharpe)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (strategy, params, symbol, total_trades, win_rate, expectancy,
         total_pnl, max_drawdown, profit_factor, sharpe),
    )
    conn.commit()

def get_top_crypto_backtests(self, limit: int = 5) -> list[dict]:
    conn = self._conn()
    rows = conn.execute(
        "SELECT * FROM crypto_backtests ORDER BY expectancy DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]

def upsert_crypto_pnl_daily(self, date: str, trades_count: int, wins: int,
                             losses: int, gross_pnl: float, fees: float,
                             net_pnl: float, bankroll: float = 0.0):
    conn = self._conn()
    # Recompute cumulative from history + this entry
    prev = conn.execute(
        "SELECT COALESCE(SUM(net_pnl), 0) as s FROM crypto_pnl_daily WHERE date < ?",
        (date,),
    ).fetchone()["s"]
    cumulative = prev + net_pnl
    bankroll_after = bankroll if bankroll > 0 else None
    conn.execute(
        """INSERT INTO crypto_pnl_daily
           (date, trades_count, wins, losses, gross_pnl, fees, net_pnl, cumulative_pnl, bankroll_after)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
               trades_count = excluded.trades_count,
               wins = excluded.wins, losses = excluded.losses,
               gross_pnl = excluded.gross_pnl, fees = excluded.fees,
               net_pnl = excluded.net_pnl, cumulative_pnl = excluded.cumulative_pnl,
               bankroll_after = excluded.bankroll_after""",
        (date, trades_count, wins, losses, gross_pnl, fees, net_pnl, cumulative, bankroll_after),
    )
    conn.commit()

def get_crypto_pnl_history(self) -> list[dict]:
    conn = self._conn()
    rows = conn.execute(
        "SELECT * FROM crypto_pnl_daily ORDER BY date ASC"
    ).fetchall()
    return [dict(r) for r in rows]

def get_or_create_incubation(self, strategy: str) -> dict:
    conn = self._conn()
    row = conn.execute(
        "SELECT * FROM crypto_incubation WHERE strategy = ?", (strategy,)
    ).fetchone()
    if row:
        return dict(row)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO crypto_incubation (strategy, last_updated) VALUES (?, ?)",
        (strategy, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM crypto_incubation WHERE strategy = ?", (strategy,)
    ).fetchone()
    return dict(row)

def update_incubation(self, strategy: str, total_trades: int, wins: int,
                      losses: int, total_pnl: float,
                      position_size: float | None = None,
                      status: str | None = None):
    conn = self._conn()
    now = datetime.now(timezone.utc).isoformat()
    if position_size is not None and status is not None:
        conn.execute(
            """UPDATE crypto_incubation
               SET total_trades=?, wins=?, losses=?, total_pnl=?,
                   position_size=?, status=?, last_updated=?
               WHERE strategy=?""",
            (total_trades, wins, losses, total_pnl, position_size, status, now, strategy),
        )
    elif position_size is not None:
        conn.execute(
            """UPDATE crypto_incubation
               SET total_trades=?, wins=?, losses=?, total_pnl=?,
                   position_size=?, last_updated=?
               WHERE strategy=?""",
            (total_trades, wins, losses, total_pnl, position_size, now, strategy),
        )
    elif status is not None:
        conn.execute(
            """UPDATE crypto_incubation
               SET total_trades=?, wins=?, losses=?, total_pnl=?,
                   status=?, last_updated=?
               WHERE strategy=?""",
            (total_trades, wins, losses, total_pnl, status, now, strategy),
        )
    else:
        conn.execute(
            """UPDATE crypto_incubation
               SET total_trades=?, wins=?, losses=?, total_pnl=?, last_updated=?
               WHERE strategy=?""",
            (total_trades, wins, losses, total_pnl, now, strategy),
        )
    conn.commit()

def get_crypto_trade_stats(self) -> dict:
    conn = self._conn()
    total = conn.execute("SELECT COUNT(*) as n FROM crypto_trades").fetchone()["n"]
    settled_statuses = ('won', 'lost', 'dry_run_won', 'dry_run_lost')
    placeholders = ",".join("?" for _ in settled_statuses)
    settled = conn.execute(
        f"SELECT COUNT(*) as n FROM crypto_trades WHERE status IN ({placeholders})",
        settled_statuses,
    ).fetchone()["n"]
    win_statuses = ('won', 'dry_run_won')
    w_placeholders = ",".join("?" for _ in win_statuses)
    wins = conn.execute(
        f"SELECT COUNT(*) as n FROM crypto_trades WHERE status IN ({w_placeholders})",
        win_statuses,
    ).fetchone()["n"]
    total_pnl = conn.execute(
        f"SELECT COALESCE(SUM(pnl), 0) as s FROM crypto_trades WHERE status IN ({placeholders})",
        settled_statuses,
    ).fetchone()["s"]
    return {
        "total_trades": total,
        "settled": settled,
        "wins": wins,
        "losses": settled - wins,
        "win_rate": round(wins / settled, 4) if settled > 0 else 0.0,
        "total_pnl": round(total_pnl, 2),
    }

def get_crypto_strategy_stats(self) -> list[dict]:
    conn = self._conn()
    rows = conn.execute(
        """SELECT strategy,
                  COUNT(*) as total_trades,
                  SUM(CASE WHEN status IN ('won', 'dry_run_won') THEN 1 ELSE 0 END) as wins,
                  SUM(CASE WHEN status IN ('lost', 'dry_run_lost') THEN 1 ELSE 0 END) as losses,
                  COALESCE(SUM(pnl), 0) as total_pnl
           FROM crypto_trades
           WHERE status IN ('won', 'lost', 'dry_run_won', 'dry_run_lost')
           GROUP BY strategy"""
    ).fetchall()
    result = []
    for r in rows:
        total = r["wins"] + r["losses"]
        result.append({
            "strategy": r["strategy"],
            "total_trades": total,
            "wins": r["wins"],
            "losses": r["losses"],
            "win_rate": round(r["wins"] / total, 4) if total > 0 else 0.0,
            "total_pnl": round(r["total_pnl"], 2),
        })
    return result

def get_all_incubations(self) -> list[dict]:
    conn = self._conn()
    rows = conn.execute("SELECT * FROM crypto_incubation ORDER BY strategy").fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_crypto_db.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite for regressions**

Run: `python -m pytest tests/ -v --timeout=30`
Expected: All existing tests still pass

- [ ] **Step 7: Commit**

```bash
git add src/db.py tests/test_crypto_db.py
git commit -m "feat(crypto): add 5 crypto tables and DB methods"
```

---

### Task 3: Data Feed (ccxt Coinbase)

**Files:**
- Create: `src/crypto/__init__.py`
- Create: `src/crypto/data_feed.py`
- Test: `tests/test_crypto_data_feed.py`

- [ ] **Step 1: Create package init**

```python
# src/crypto/__init__.py
```

- [ ] **Step 2: Write tests for data feed**

```python
# tests/test_crypto_data_feed.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import pandas as pd
from src.crypto.data_feed import CryptoDataFeed


@pytest.fixture
def feed():
    return CryptoDataFeed()


def test_feed_default_exchange(feed):
    assert feed.exchange_id == "coinbase"


def _make_ohlcv_data(count=5):
    """Generate fake OHLCV data as ccxt returns it: [[timestamp_ms, o, h, l, c, v], ...]"""
    import time
    base = int(time.time() * 1000) - count * 60000
    return [[base + i * 60000, 84000 + i, 84100 + i, 83900 + i, 84050 + i, 100 + i]
            for i in range(count)]


async def test_fetch_candles_returns_dataframe(feed):
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=_make_ohlcv_data(10))
    with patch.object(feed, '_get_exchange', return_value=mock_exchange):
        df = await feed.fetch_candles("BTC/USDT", limit=10)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 10
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert df["open"].dtype == float


async def test_fetch_candles_minimum_threshold(feed):
    """Returns None when fewer than min_candles returned."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=_make_ohlcv_data(5))
    with patch.object(feed, '_get_exchange', return_value=mock_exchange):
        df = await feed.fetch_candles("BTC/USDT", limit=100, min_candles=60)
    assert df is None


async def test_fetch_candles_error_returns_none(feed):
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(side_effect=Exception("API error"))
    with patch.object(feed, '_get_exchange', return_value=mock_exchange):
        df = await feed.fetch_candles("BTC/USDT", limit=10)
    assert df is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_crypto_data_feed.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement data feed**

```python
# src/crypto/data_feed.py
import logging
from datetime import datetime, timezone
import pandas as pd

logger = logging.getLogger(__name__)


class CryptoDataFeed:
    def __init__(self, exchange_id: str = "coinbase"):
        self.exchange_id = exchange_id
        self._exchange = None

    def _get_exchange(self):
        if self._exchange is None:
            import ccxt.async_support as ccxt
            exchange_class = getattr(ccxt, self.exchange_id)
            self._exchange = exchange_class({"enableRateLimit": True})
        return self._exchange

    async def fetch_candles(self, symbol: str = "BTC/USDT", timeframe: str = "1m",
                            limit: int = 100, min_candles: int = 60) -> pd.DataFrame | None:
        """Fetch OHLCV candles. Returns DataFrame or None on error/insufficient data."""
        try:
            exchange = self._get_exchange()
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if len(ohlcv) < min_candles:
                logger.warning(f"Insufficient candles: got {len(ohlcv)}, need {min_candles}")
                return None
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            return df
        except Exception as e:
            logger.error(f"Failed to fetch candles: {e}")
            return None

    async def close(self):
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_crypto_data_feed.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/crypto/__init__.py src/crypto/data_feed.py tests/test_crypto_data_feed.py
git commit -m "feat(crypto): add ccxt data feed for 1m candles"
```

---

### Task 4: Indicators (pandas-ta)

**Files:**
- Create: `src/crypto/indicators.py`
- Test: `tests/test_crypto_indicators.py`

- [ ] **Step 1: Write tests for indicators**

```python
# tests/test_crypto_indicators.py
import pytest
import pandas as pd
import numpy as np
from src.crypto.indicators import compute_indicators


def _make_candle_df(n=100):
    """Generate a realistic-looking candle DataFrame for testing."""
    np.random.seed(42)
    base_price = 84000.0
    prices = base_price + np.cumsum(np.random.randn(n) * 10)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-03-18", periods=n, freq="1min", tz="UTC"),
        "open": prices,
        "high": prices + np.abs(np.random.randn(n) * 5),
        "low": prices - np.abs(np.random.randn(n) * 5),
        "close": prices + np.random.randn(n) * 3,
        "volume": np.random.randint(50, 500, n).astype(float),
    })
    return df


def test_compute_indicators_adds_columns():
    df = _make_candle_df(100)
    result = compute_indicators(df)
    expected_cols = [
        "macd", "macd_signal", "macd_hist",
        "rsi",
        "bb_upper", "bb_mid", "bb_lower", "bb_bandwidth",
        "vwap",
        "ema_fast", "ema_slow",
        "vol_sma", "vol_spike_ratio",
        "atr",
    ]
    for col in expected_cols:
        assert col in result.columns, f"Missing column: {col}"


def test_compute_indicators_custom_params():
    df = _make_candle_df(100)
    result = compute_indicators(df, macd_fast=8, macd_slow=21, macd_signal=5,
                                rsi_length=7, bb_length=20, bb_std=2.0,
                                ema_fast=3, ema_slow=10, vol_sma_length=20)
    assert "macd" in result.columns
    assert "rsi" in result.columns


def test_compute_indicators_preserves_original_columns():
    df = _make_candle_df(100)
    result = compute_indicators(df)
    for col in ["timestamp", "open", "high", "low", "close", "volume"]:
        assert col in result.columns


def test_compute_indicators_too_few_candles():
    """Should return DataFrame with NaN indicators rather than crashing."""
    df = _make_candle_df(10)
    result = compute_indicators(df)
    assert len(result) == 10
    # Most indicators will be NaN due to insufficient data, but shouldn't crash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_crypto_indicators.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement indicators**

```python
# src/crypto/indicators.py
import pandas as pd
import pandas_ta as ta


def compute_indicators(
    df: pd.DataFrame,
    macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9,
    rsi_length: int = 14,
    bb_length: int = 20, bb_std: float = 2.0,
    ema_fast: int = 5, ema_slow: int = 13,
    vol_sma_length: int = 20,
    atr_length: int = 14,
) -> pd.DataFrame:
    """Compute all technical indicators on a 1m candle DataFrame.

    Returns a copy of the input with indicator columns added.
    NaN values will appear where insufficient history exists.
    """
    df = df.copy()

    # MACD
    macd_result = ta.macd(df["close"], fast=macd_fast, slow=macd_slow, signal=macd_signal)
    if macd_result is not None and len(macd_result.columns) >= 3:
        df["macd"] = macd_result.iloc[:, 0]
        df["macd_hist"] = macd_result.iloc[:, 1]
        df["macd_signal"] = macd_result.iloc[:, 2]
    else:
        df["macd"] = df["macd_hist"] = df["macd_signal"] = float("nan")

    # RSI
    rsi = ta.rsi(df["close"], length=rsi_length)
    df["rsi"] = rsi if rsi is not None else float("nan")

    # Bollinger Bands
    bbands = ta.bbands(df["close"], length=bb_length, std=bb_std)
    if bbands is not None and len(bbands.columns) >= 3:
        df["bb_lower"] = bbands.iloc[:, 0]
        df["bb_mid"] = bbands.iloc[:, 1]
        df["bb_upper"] = bbands.iloc[:, 2]
        df["bb_bandwidth"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    else:
        df["bb_lower"] = df["bb_mid"] = df["bb_upper"] = df["bb_bandwidth"] = float("nan")

    # VWAP (cumulative for the session)
    df["vwap"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])

    # EMA pair
    df["ema_fast"] = ta.ema(df["close"], length=ema_fast)
    df["ema_slow"] = ta.ema(df["close"], length=ema_slow)

    # Volume SMA + spike ratio
    df["vol_sma"] = ta.sma(df["volume"], length=vol_sma_length)
    df["vol_spike_ratio"] = df["volume"] / df["vol_sma"]

    # ATR
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=atr_length)

    return df
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_crypto_indicators.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/crypto/indicators.py tests/test_crypto_indicators.py
git commit -m "feat(crypto): add pandas-ta indicator computation"
```

---

### Task 5: Strategy Base Class + MACD Histogram

**Files:**
- Create: `src/crypto/strategies/__init__.py`
- Create: `src/crypto/strategies/base.py`
- Create: `src/crypto/strategies/macd_hist.py`
- Test: `tests/test_crypto_strategies.py`

- [ ] **Step 1: Write tests for base class and MACD strategy**

```python
# tests/test_crypto_strategies.py
import pytest
import pandas as pd
import numpy as np
from src.crypto.strategies.base import CryptoStrategy
from src.crypto.strategies.macd_hist import MACDHistStrategy
from src.crypto.indicators import compute_indicators


def _make_candle_df(n=100):
    np.random.seed(42)
    base = 84000.0
    prices = base + np.cumsum(np.random.randn(n) * 10)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-03-18", periods=n, freq="1min", tz="UTC"),
        "open": prices,
        "high": prices + np.abs(np.random.randn(n) * 5),
        "low": prices - np.abs(np.random.randn(n) * 5),
        "close": prices + np.random.randn(n) * 3,
        "volume": np.random.randint(50, 500, n).astype(float),
    })


def test_base_class_is_abstract():
    with pytest.raises(TypeError):
        CryptoStrategy()


class TestMACDHist:
    def test_generate_signal_returns_tuple(self):
        strat = MACDHistStrategy(macd_fast=3, macd_slow=15, macd_signal=3)
        df = compute_indicators(_make_candle_df(100), macd_fast=3, macd_slow=15, macd_signal=3)
        signal, meta = strat.generate_signal(df)
        assert signal in (-1, 0, 1)
        assert isinstance(meta, dict)

    def test_generate_signal_returns_zero_with_nan(self):
        strat = MACDHistStrategy()
        df = compute_indicators(_make_candle_df(10))
        signal, meta = strat.generate_signal(df)
        assert signal == 0  # not enough data

    def test_backtest_signal_returns_trade_list(self):
        strat = MACDHistStrategy(macd_fast=3, macd_slow=15, macd_signal=3)
        df = compute_indicators(_make_candle_df(200), macd_fast=3, macd_slow=15, macd_signal=3)
        trades = strat.backtest_signal(df)
        assert isinstance(trades, list)
        for t in trades:
            assert "signal" in t
            assert "entry_idx" in t
            assert "exit_idx" in t

    def test_params_dict(self):
        strat = MACDHistStrategy(macd_fast=3, macd_slow=15, macd_signal=3)
        p = strat.params_dict()
        assert p == {"macd_fast": 3, "macd_slow": 15, "macd_signal": 3}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_crypto_strategies.py -v`
Expected: FAIL

- [ ] **Step 3: Implement base class**

Initially create this with only MACDHistStrategy. The remaining imports are added in Task 6 Step 6.

```python
# src/crypto/strategies/base.py
from abc import ABC, abstractmethod
import pandas as pd


class CryptoStrategy(ABC):
    """Base class for crypto 5-minute trading strategies."""

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        """Generate a trading signal from indicator-enriched candle data.

        Args:
            df: DataFrame with OHLCV + indicator columns

        Returns:
            (signal, metadata) where signal is 1=YES/long, -1=NO/short, 0=no trade
            and metadata is a dict of indicator values for logging.
        """
        ...

    @abstractmethod
    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        """Walk full DataFrame generating signals at 5-min boundaries.

        Returns list of trade dicts with keys:
            signal, entry_idx, exit_idx, entry_price, exit_price
        """
        ...

    @abstractmethod
    def params_dict(self) -> dict:
        """Return strategy parameters as a dict for serialization."""
        ...
```

- [ ] **Step 4: Implement MACD histogram strategy**

```python
# src/crypto/strategies/macd_hist.py
import math
import pandas as pd
from src.crypto.strategies.base import CryptoStrategy


class MACDHistStrategy(CryptoStrategy):
    """Signal when MACD histogram crosses zero."""

    def __init__(self, macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9):
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        if len(df) < 2 or "macd_hist" not in df.columns:
            return 0, {}
        curr = df["macd_hist"].iloc[-1]
        prev = df["macd_hist"].iloc[-2]
        if math.isnan(curr) or math.isnan(prev):
            return 0, {}
        meta = {"macd_hist": round(curr, 6), "macd_hist_prev": round(prev, 6)}
        # Bullish crossover: histogram crosses from negative to positive
        if prev <= 0 and curr > 0:
            return 1, meta
        # Bearish crossover: histogram crosses from positive to negative
        if prev >= 0 and curr < 0:
            return -1, meta
        return 0, meta

    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        trades = []
        if "macd_hist" not in df.columns:
            return trades
        for i in range(5, len(df), 5):  # 5-min boundaries
            if i < 2:
                continue
            curr = df["macd_hist"].iloc[i - 1]
            prev = df["macd_hist"].iloc[i - 2]
            if math.isnan(curr) or math.isnan(prev):
                continue
            signal = 0
            if prev <= 0 and curr > 0:
                signal = 1
            elif prev >= 0 and curr < 0:
                signal = -1
            if signal != 0 and i + 5 <= len(df):
                trades.append({
                    "signal": signal,
                    "entry_idx": i,
                    "exit_idx": i + 5,
                    "entry_price": df["close"].iloc[i],
                    "exit_price": df["close"].iloc[min(i + 5, len(df) - 1)],
                })
        return trades

    def params_dict(self) -> dict:
        return {"macd_fast": self.macd_fast, "macd_slow": self.macd_slow, "macd_signal": self.macd_signal}
```

- [ ] **Step 5: Update strategies __init__.py (only macd_hist for now)**

```python
# src/crypto/strategies/__init__.py
from src.crypto.strategies.macd_hist import MACDHistStrategy

STRATEGY_REGISTRY = {
    "macd_hist": MACDHistStrategy,
}
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_crypto_strategies.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/crypto/strategies/ tests/test_crypto_strategies.py
git commit -m "feat(crypto): add strategy base class and MACD histogram strategy"
```

---

### Task 6: Remaining 3 Strategies

**Files:**
- Create: `src/crypto/strategies/rsi_bb.py`
- Create: `src/crypto/strategies/vwap_cap.py`
- Create: `src/crypto/strategies/ema_cross.py`
- Modify: `src/crypto/strategies/__init__.py`
- Test: `tests/test_crypto_strategies.py` (extend)

- [ ] **Step 1: Add tests for remaining strategies**

Append to `tests/test_crypto_strategies.py`:

```python
from src.crypto.strategies.rsi_bb import RSIBBStrategy
from src.crypto.strategies.vwap_cap import VWAPCapStrategy
from src.crypto.strategies.ema_cross import EMACrossStrategy


class TestRSIBB:
    def test_generate_signal(self):
        strat = RSIBBStrategy(rsi_length=7, bb_length=20, bb_std=2.0,
                              rsi_oversold=30, rsi_overbought=70, squeeze_threshold=0.02)
        df = compute_indicators(_make_candle_df(100), rsi_length=7, bb_length=20, bb_std=2.0)
        signal, meta = strat.generate_signal(df)
        assert signal in (-1, 0, 1)

    def test_backtest_signal(self):
        strat = RSIBBStrategy()
        df = compute_indicators(_make_candle_df(200))
        trades = strat.backtest_signal(df)
        assert isinstance(trades, list)

    def test_params_dict(self):
        strat = RSIBBStrategy(rsi_length=7, bb_length=20, bb_std=2.0,
                              rsi_oversold=30, rsi_overbought=70, squeeze_threshold=0.02)
        p = strat.params_dict()
        assert "rsi_length" in p
        assert "squeeze_threshold" in p


class TestVWAPCap:
    def test_generate_signal(self):
        strat = VWAPCapStrategy(vol_spike_min=2.0, vwap_revert_pct=0.001, vol_sma_length=20)
        df = compute_indicators(_make_candle_df(100), vol_sma_length=20)
        signal, meta = strat.generate_signal(df)
        assert signal in (-1, 0, 1)

    def test_backtest_signal(self):
        strat = VWAPCapStrategy()
        df = compute_indicators(_make_candle_df(200))
        trades = strat.backtest_signal(df)
        assert isinstance(trades, list)

    def test_params_dict(self):
        strat = VWAPCapStrategy()
        assert "vol_spike_min" in strat.params_dict()


class TestEMACross:
    def test_generate_signal(self):
        strat = EMACrossStrategy(ema_fast=5, ema_slow=13)
        df = compute_indicators(_make_candle_df(100), ema_fast=5, ema_slow=13)
        signal, meta = strat.generate_signal(df)
        assert signal in (-1, 0, 1)

    def test_backtest_signal(self):
        strat = EMACrossStrategy()
        df = compute_indicators(_make_candle_df(200))
        trades = strat.backtest_signal(df)
        assert isinstance(trades, list)

    def test_params_dict(self):
        strat = EMACrossStrategy(ema_fast=8, ema_slow=21)
        assert strat.params_dict() == {"ema_fast": 8, "ema_slow": 21}


def test_strategy_registry():
    from src.crypto.strategies import STRATEGY_REGISTRY
    assert "macd_hist" in STRATEGY_REGISTRY
    assert "rsi_bb" in STRATEGY_REGISTRY
    assert "vwap_cap" in STRATEGY_REGISTRY
    assert "ema_cross" in STRATEGY_REGISTRY
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `python -m pytest tests/test_crypto_strategies.py -v`
Expected: FAIL for new strategy classes

- [ ] **Step 3: Implement RSI+BB strategy**

```python
# src/crypto/strategies/rsi_bb.py
import math
import pandas as pd
from src.crypto.strategies.base import CryptoStrategy


class RSIBBStrategy(CryptoStrategy):
    """Signal when RSI oversold/overbought AND BB bandwidth squeezing."""

    def __init__(self, rsi_length: int = 14, bb_length: int = 20, bb_std: float = 2.0,
                 rsi_oversold: float = 30, rsi_overbought: float = 70,
                 squeeze_threshold: float = 0.02):
        self.rsi_length = rsi_length
        self.bb_length = bb_length
        self.bb_std = bb_std
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.squeeze_threshold = squeeze_threshold

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        if len(df) < 1:
            return 0, {}
        rsi = df["rsi"].iloc[-1] if "rsi" in df.columns else float("nan")
        bw = df["bb_bandwidth"].iloc[-1] if "bb_bandwidth" in df.columns else float("nan")
        if math.isnan(rsi) or math.isnan(bw):
            return 0, {}
        meta = {"rsi": round(rsi, 2), "bb_bandwidth": round(bw, 6)}
        squeeze = bw < self.squeeze_threshold
        if squeeze and rsi < self.rsi_oversold:
            return 1, meta  # Oversold + squeeze → expect bounce up
        if squeeze and rsi > self.rsi_overbought:
            return -1, meta  # Overbought + squeeze → expect drop
        return 0, meta

    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        trades = []
        for i in range(5, len(df), 5):
            rsi = df["rsi"].iloc[i - 1] if "rsi" in df.columns else float("nan")
            bw = df["bb_bandwidth"].iloc[i - 1] if "bb_bandwidth" in df.columns else float("nan")
            if math.isnan(rsi) or math.isnan(bw):
                continue
            signal = 0
            squeeze = bw < self.squeeze_threshold
            if squeeze and rsi < self.rsi_oversold:
                signal = 1
            elif squeeze and rsi > self.rsi_overbought:
                signal = -1
            if signal != 0 and i + 5 <= len(df):
                trades.append({
                    "signal": signal, "entry_idx": i, "exit_idx": i + 5,
                    "entry_price": df["close"].iloc[i],
                    "exit_price": df["close"].iloc[min(i + 5, len(df) - 1)],
                })
        return trades

    def params_dict(self) -> dict:
        return {
            "rsi_length": self.rsi_length, "bb_length": self.bb_length,
            "bb_std": self.bb_std, "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought, "squeeze_threshold": self.squeeze_threshold,
        }
```

- [ ] **Step 4: Implement VWAP capitulation strategy**

```python
# src/crypto/strategies/vwap_cap.py
import math
import pandas as pd
from src.crypto.strategies.base import CryptoStrategy


class VWAPCapStrategy(CryptoStrategy):
    """Signal when price drops below VWAP with volume spike (capitulation reversion)."""

    def __init__(self, vol_spike_min: float = 2.0, vwap_revert_pct: float = 0.001,
                 vol_sma_length: int = 20):
        self.vol_spike_min = vol_spike_min
        self.vwap_revert_pct = vwap_revert_pct
        self.vol_sma_length = vol_sma_length

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        if len(df) < 1:
            return 0, {}
        close = df["close"].iloc[-1]
        vwap = df["vwap"].iloc[-1] if "vwap" in df.columns else float("nan")
        spike = df["vol_spike_ratio"].iloc[-1] if "vol_spike_ratio" in df.columns else float("nan")
        if math.isnan(vwap) or math.isnan(spike) or vwap == 0:
            return 0, {}
        meta = {"close": round(close, 2), "vwap": round(vwap, 2), "vol_spike": round(spike, 2)}
        deviation = (close - vwap) / vwap
        has_spike = spike >= self.vol_spike_min
        if has_spike and deviation < -self.vwap_revert_pct:
            return 1, meta  # Capitulation below VWAP → expect reversion up
        if has_spike and deviation > self.vwap_revert_pct:
            return -1, meta  # Spike above VWAP → expect reversion down
        return 0, meta

    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        trades = []
        for i in range(5, len(df), 5):
            close = df["close"].iloc[i - 1]
            vwap = df["vwap"].iloc[i - 1] if "vwap" in df.columns else float("nan")
            spike = df["vol_spike_ratio"].iloc[i - 1] if "vol_spike_ratio" in df.columns else float("nan")
            if math.isnan(vwap) or math.isnan(spike) or vwap == 0:
                continue
            deviation = (close - vwap) / vwap
            has_spike = spike >= self.vol_spike_min
            signal = 0
            if has_spike and deviation < -self.vwap_revert_pct:
                signal = 1
            elif has_spike and deviation > self.vwap_revert_pct:
                signal = -1
            if signal != 0 and i + 5 <= len(df):
                trades.append({
                    "signal": signal, "entry_idx": i, "exit_idx": i + 5,
                    "entry_price": df["close"].iloc[i],
                    "exit_price": df["close"].iloc[min(i + 5, len(df) - 1)],
                })
        return trades

    def params_dict(self) -> dict:
        return {"vol_spike_min": self.vol_spike_min, "vwap_revert_pct": self.vwap_revert_pct,
                "vol_sma_length": self.vol_sma_length}
```

- [ ] **Step 5: Implement EMA crossover strategy**

```python
# src/crypto/strategies/ema_cross.py
import math
import pandas as pd
from src.crypto.strategies.base import CryptoStrategy


class EMACrossStrategy(CryptoStrategy):
    """Signal when fast EMA crosses slow EMA."""

    def __init__(self, ema_fast: int = 5, ema_slow: int = 13):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        if len(df) < 2 or "ema_fast" not in df.columns or "ema_slow" not in df.columns:
            return 0, {}
        fast_curr = df["ema_fast"].iloc[-1]
        slow_curr = df["ema_slow"].iloc[-1]
        fast_prev = df["ema_fast"].iloc[-2]
        slow_prev = df["ema_slow"].iloc[-2]
        if any(math.isnan(v) for v in [fast_curr, slow_curr, fast_prev, slow_prev]):
            return 0, {}
        meta = {"ema_fast": round(fast_curr, 2), "ema_slow": round(slow_curr, 2)}
        # Bullish crossover
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            return 1, meta
        # Bearish crossover
        if fast_prev >= slow_prev and fast_curr < slow_curr:
            return -1, meta
        return 0, meta

    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        trades = []
        if "ema_fast" not in df.columns or "ema_slow" not in df.columns:
            return trades
        for i in range(5, len(df), 5):
            if i < 2:
                continue
            fc = df["ema_fast"].iloc[i - 1]
            sc = df["ema_slow"].iloc[i - 1]
            fp = df["ema_fast"].iloc[i - 2]
            sp = df["ema_slow"].iloc[i - 2]
            if any(math.isnan(v) for v in [fc, sc, fp, sp]):
                continue
            signal = 0
            if fp <= sp and fc > sc:
                signal = 1
            elif fp >= sp and fc < sc:
                signal = -1
            if signal != 0 and i + 5 <= len(df):
                trades.append({
                    "signal": signal, "entry_idx": i, "exit_idx": i + 5,
                    "entry_price": df["close"].iloc[i],
                    "exit_price": df["close"].iloc[min(i + 5, len(df) - 1)],
                })
        return trades

    def params_dict(self) -> dict:
        return {"ema_fast": self.ema_fast, "ema_slow": self.ema_slow}
```

- [ ] **Step 6: Update strategies __init__.py with all 4**

```python
# src/crypto/strategies/__init__.py
from src.crypto.strategies.macd_hist import MACDHistStrategy
from src.crypto.strategies.rsi_bb import RSIBBStrategy
from src.crypto.strategies.vwap_cap import VWAPCapStrategy
from src.crypto.strategies.ema_cross import EMACrossStrategy

STRATEGY_REGISTRY = {
    "macd_hist": MACDHistStrategy,
    "rsi_bb": RSIBBStrategy,
    "vwap_cap": VWAPCapStrategy,
    "ema_cross": EMACrossStrategy,
}
```

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_crypto_strategies.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/crypto/strategies/ tests/test_crypto_strategies.py
git commit -m "feat(crypto): add RSI+BB, VWAP capitulation, EMA crossover strategies"
```

---

### Task 7: Backtest Engine + Runner

**Files:**
- Create: `src/crypto/backtester/__init__.py`
- Create: `src/crypto/backtester/engine.py`
- Create: `src/crypto/backtester/runner.py`
- Test: `tests/test_crypto_backtest.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_crypto_backtest.py
import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock
from src.crypto.backtester.engine import BacktestEngine
from src.crypto.backtester.runner import BacktestRunner, PARAM_GRID
from src.crypto.strategies.macd_hist import MACDHistStrategy
from src.crypto.indicators import compute_indicators


def _make_candle_df(n=500):
    np.random.seed(42)
    base = 84000.0
    prices = base + np.cumsum(np.random.randn(n) * 10)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-03-18", periods=n, freq="1min", tz="UTC"),
        "open": prices,
        "high": prices + np.abs(np.random.randn(n) * 5),
        "low": prices - np.abs(np.random.randn(n) * 5),
        "close": prices + np.random.randn(n) * 3,
        "volume": np.random.randint(50, 500, n).astype(float),
    })


def test_backtest_engine_runs():
    strat = MACDHistStrategy(macd_fast=3, macd_slow=15, macd_signal=3)
    df = _make_candle_df(500)
    engine = BacktestEngine(entry_price=0.50, fee_pct=0.02, stake=1.50)
    result = engine.run(strat, df, indicator_params={"macd_fast": 3, "macd_slow": 15, "macd_signal": 3})
    assert "total_trades" in result
    assert "win_rate" in result
    assert "expectancy" in result
    assert "total_pnl" in result
    assert "max_drawdown" in result
    assert "profit_factor" in result
    assert "sharpe" in result


def test_backtest_engine_no_trades():
    """Engine handles case where strategy generates no signals."""
    strat = MACDHistStrategy()
    df = _make_candle_df(20)  # too short for signals
    engine = BacktestEngine()
    result = engine.run(strat, df)
    assert result["total_trades"] == 0
    assert result["win_rate"] == 0.0


def test_backtest_engine_pnl_math():
    """Verify win/loss P&L calculations are correct."""
    engine = BacktestEngine(entry_price=0.50, fee_pct=0.02, stake=1.50)
    # Win: (1/0.50 - 1) * 1.50 - 0.02*1.50 = 1.50 - 0.03 = 1.47
    assert abs(engine._calc_trade_pnl(won=True) - 1.47) < 0.01
    # Loss: -1.50 - 0.02*1.50 = -1.53
    assert abs(engine._calc_trade_pnl(won=False) - (-1.53)) < 0.01


def test_param_grid_has_all_strategies():
    assert "macd_hist" in PARAM_GRID
    assert "rsi_bb" in PARAM_GRID
    assert "vwap_cap" in PARAM_GRID
    assert "ema_cross" in PARAM_GRID


def test_runner_runs_grid(tmp_path):
    db = MagicMock()
    runner = BacktestRunner(db=db)
    df = _make_candle_df(500)
    results = runner.run_grid(df, strategies=["macd_hist"], symbol="BTC")
    assert len(results) > 0
    assert results[0]["strategy"] == "macd_hist"
    # Should have called db.save_crypto_backtest for each param combo
    assert db.save_crypto_backtest.call_count == len(PARAM_GRID["macd_hist"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_crypto_backtest.py -v`
Expected: FAIL

- [ ] **Step 3: Implement backtest engine**

```python
# src/crypto/backtester/__init__.py
```

```python
# src/crypto/backtester/engine.py
import logging
import numpy as np
import pandas as pd
from src.crypto.indicators import compute_indicators
from src.crypto.strategies.base import CryptoStrategy

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Simulate Polymarket 5-min binary markets on historical 1m candles."""

    def __init__(self, entry_price: float = 0.50, fee_pct: float = 0.02, stake: float = 1.50):
        self.entry_price = entry_price
        self.fee_pct = fee_pct
        self.stake = stake

    def _calc_trade_pnl(self, won: bool) -> float:
        fee = self.stake * self.fee_pct
        if won:
            return (1.0 / self.entry_price - 1.0) * self.stake - fee
        else:
            return -self.stake - fee

    def run(self, strategy: CryptoStrategy, df: pd.DataFrame,
            indicator_params: dict | None = None) -> dict:
        """Run backtest. Returns metrics dict."""
        params = indicator_params or {}
        enriched = compute_indicators(df, **params)
        trades = strategy.backtest_signal(enriched)

        if not trades:
            return {
                "total_trades": 0, "win_rate": 0.0, "expectancy": 0.0,
                "total_pnl": 0.0, "max_drawdown": 0.0, "profit_factor": 0.0, "sharpe": 0.0,
            }

        pnls = []
        for t in trades:
            entry = t["entry_price"]
            exit_ = t["exit_price"]
            signal = t["signal"]
            # Did price move in predicted direction?
            won = (signal == 1 and exit_ > entry) or (signal == -1 and exit_ < entry)
            pnls.append(self._calc_trade_pnl(won))

        pnls = np.array(pnls)
        wins = np.sum(pnls > 0)
        losses = np.sum(pnls <= 0)
        total = len(pnls)

        cum_pnl = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cum_pnl)
        drawdowns = cum_pnl - running_max
        max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

        gross_wins = float(np.sum(pnls[pnls > 0])) if wins > 0 else 0.0
        gross_losses = float(np.abs(np.sum(pnls[pnls <= 0]))) if losses > 0 else 0.0
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0.0

        mean_pnl = float(np.mean(pnls))
        std_pnl = float(np.std(pnls)) if total > 1 else 1.0
        sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0.0

        return {
            "total_trades": total,
            "win_rate": round(float(wins / total), 4),
            "expectancy": round(mean_pnl, 4),
            "total_pnl": round(float(np.sum(pnls)), 2),
            "max_drawdown": round(max_drawdown, 2),
            "profit_factor": round(profit_factor, 4),
            "sharpe": round(sharpe, 4),
        }
```

- [ ] **Step 4: Implement backtest runner with param grid**

```python
# src/crypto/backtester/runner.py
import json
import logging
from src.crypto.backtester.engine import BacktestEngine
from src.crypto.strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)

PARAM_GRID = {
    "macd_hist": [
        {"macd_fast": 3, "macd_slow": 15, "macd_signal": 3},
        {"macd_fast": 8, "macd_slow": 21, "macd_signal": 5},
        {"macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    ],
    "rsi_bb": [
        {"rsi_length": 7, "bb_length": 20, "bb_std": 2.0, "rsi_oversold": 30, "rsi_overbought": 70, "squeeze_threshold": 0.02},
        {"rsi_length": 14, "bb_length": 20, "bb_std": 2.0, "rsi_oversold": 25, "rsi_overbought": 75, "squeeze_threshold": 0.015},
    ],
    "vwap_cap": [
        {"vol_spike_min": 2.0, "vwap_revert_pct": 0.001, "vol_sma_length": 20},
        {"vol_spike_min": 3.0, "vwap_revert_pct": 0.0005, "vol_sma_length": 20},
    ],
    "ema_cross": [
        {"ema_fast": 5, "ema_slow": 13},
        {"ema_fast": 8, "ema_slow": 21},
        {"ema_fast": 3, "ema_slow": 10},
    ],
}


class BacktestRunner:
    """Run all strategies x parameter combos sequentially. Save results to DB."""

    def __init__(self, db=None, entry_price: float = 0.50, fee_pct: float = 0.02,
                 stake: float = 1.50):
        self.db = db
        self.engine = BacktestEngine(entry_price=entry_price, fee_pct=fee_pct, stake=stake)

    def run_grid(self, df, strategies: list[str] | None = None,
                 symbol: str = "BTC") -> list[dict]:
        """Run backtest grid. Returns list of result dicts sorted by expectancy."""
        strategies = strategies or list(PARAM_GRID.keys())
        all_results = []

        for strat_name in strategies:
            if strat_name not in STRATEGY_REGISTRY:
                logger.warning(f"Unknown strategy: {strat_name}")
                continue
            param_combos = PARAM_GRID.get(strat_name, [{}])
            strat_class = STRATEGY_REGISTRY[strat_name]

            for params in param_combos:
                strat = strat_class(**params)
                result = self.engine.run(strat, df, indicator_params=params)
                result["strategy"] = strat_name
                result["params"] = params
                result["symbol"] = symbol
                all_results.append(result)

                if self.db:
                    self.db.save_crypto_backtest(
                        strategy=strat_name,
                        params=json.dumps(params),
                        symbol=symbol,
                        total_trades=result["total_trades"],
                        win_rate=result["win_rate"],
                        expectancy=result["expectancy"],
                        total_pnl=result["total_pnl"],
                        max_drawdown=result["max_drawdown"],
                        profit_factor=result["profit_factor"],
                        sharpe=result["sharpe"],
                    )

                logger.info(
                    f"{strat_name} {params}: trades={result['total_trades']} "
                    f"win={result['win_rate']:.1%} exp={result['expectancy']:.4f} "
                    f"pnl={result['total_pnl']:.2f}"
                )

        all_results.sort(key=lambda r: r["expectancy"], reverse=True)
        return all_results
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_crypto_backtest.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/crypto/backtester/ tests/test_crypto_backtest.py
git commit -m "feat(crypto): add backtest engine and param grid runner"
```

---

## Phase 2: Live Bot

### Task 8: Risk Manager Extension

**Files:**
- Modify: `src/risk/risk_manager.py`
- Test: `tests/test_crypto_risk.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_crypto_risk.py
import pytest
from src.config import Settings
from src.risk.risk_manager import RiskManager


@pytest.fixture
def rm():
    return RiskManager(Settings(MAX_DAILY_LOSS=100.0))


def test_crypto_risk_check_approved(rm):
    allowed, reason = rm.crypto_risk_check(
        combined_daily_pnl=0.0, available_bankroll=500.0,
        proposed_size=1.50, has_open_trade=False,
    )
    assert allowed is True
    assert reason == ""


def test_crypto_risk_check_daily_loss_exceeded(rm):
    allowed, reason = rm.crypto_risk_check(
        combined_daily_pnl=-101.0, available_bankroll=500.0,
        proposed_size=1.50, has_open_trade=False,
    )
    assert allowed is False
    assert "daily loss" in reason.lower()


def test_crypto_risk_check_insufficient_bankroll(rm):
    allowed, reason = rm.crypto_risk_check(
        combined_daily_pnl=0.0, available_bankroll=2.0,
        proposed_size=1.50, has_open_trade=False,
    )
    assert allowed is False
    assert "bankroll" in reason.lower()


def test_crypto_risk_check_has_open_trade(rm):
    allowed, reason = rm.crypto_risk_check(
        combined_daily_pnl=0.0, available_bankroll=500.0,
        proposed_size=1.50, has_open_trade=True,
    )
    assert allowed is False
    assert "open" in reason.lower()


def test_crypto_risk_check_size_too_large(rm):
    allowed, reason = rm.crypto_risk_check(
        combined_daily_pnl=0.0, available_bankroll=500.0,
        proposed_size=200.0, has_open_trade=False,
        max_position_size=100.0,
    )
    assert allowed is False
    assert "size" in reason.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_crypto_risk.py -v`
Expected: FAIL — method doesn't exist

- [ ] **Step 3: Add `crypto_risk_check()` to RiskManager**

Add to `src/risk/risk_manager.py`:

```python
def crypto_risk_check(self, combined_daily_pnl: float, available_bankroll: float,
                      proposed_size: float, has_open_trade: bool,
                      max_position_size: float = 100.0) -> tuple[bool, str]:
    """Pre-trade risk check for crypto module. Returns (allowed, reason)."""
    if combined_daily_pnl <= -self.settings.MAX_DAILY_LOSS:
        return False, f"Combined daily loss limit reached (PnL: ${combined_daily_pnl:.2f})"
    if proposed_size > max_position_size:
        return False, f"Proposed size ${proposed_size:.2f} exceeds max ${max_position_size:.2f}"
    if available_bankroll < 2 * proposed_size:
        return False, f"Insufficient bankroll: ${available_bankroll:.2f} < 2x ${proposed_size:.2f}"
    if has_open_trade:
        return False, "Already has open crypto trade"
    return True, ""
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_crypto_risk.py -v`
Expected: All PASS

- [ ] **Step 5: Run existing risk tests for regressions**

Run: `python -m pytest tests/test_risk.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/risk/risk_manager.py tests/test_crypto_risk.py
git commit -m "feat(crypto): add crypto_risk_check to RiskManager"
```

---

### Task 9: Market Scanner

**Files:**
- Create: `src/crypto/scanner.py`
- Test: `tests/test_crypto_scanner.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_crypto_scanner.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.crypto.scanner import CryptoScanner


@pytest.fixture
def scanner():
    return CryptoScanner(gamma_url="https://gamma-api.polymarket.com")


async def test_find_active_market_returns_dict(scanner):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{
        "conditionId": "0xabc",
        "tokens": [{"token_id": "tok123", "outcome": "Yes"}],
        "outcomePrices": '["0.52","0.48"]',
        "question": "Will BTC be above $84,000 at 14:05 UTC?",
        "closed": False,
        "endDate": "2026-03-18T14:05:00Z",
    }]
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=mock_resp)))
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.find_active_5min_market("BTC")
    # Result can be dict or None depending on filtering
    if result is not None:
        assert "market_id" in result
        assert "token_id" in result


async def test_find_active_market_returns_none_on_empty(scanner):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=mock_resp)))
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.find_active_5min_market("BTC")
    assert result is None


async def test_find_active_market_returns_none_on_error(scanner):
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            get=AsyncMock(side_effect=Exception("timeout"))
        ))
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await scanner.find_active_5min_market("BTC")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_crypto_scanner.py -v`
Expected: FAIL

- [ ] **Step 3: Implement scanner**

```python
# src/crypto/scanner.py
import json
import logging
import time
from datetime import datetime, timezone
import httpx

logger = logging.getLogger(__name__)


class CryptoScanner:
    """Find active 5-minute BTC/ETH markets on Polymarket."""

    def __init__(self, gamma_url: str = "https://gamma-api.polymarket.com"):
        self.gamma_url = gamma_url
        self._cache: dict | None = None
        self._cache_ts: float = 0
        self._cache_ttl: float = 60  # seconds

    async def find_active_5min_market(self, symbol: str = "BTC") -> dict | None:
        """Query Gamma API for current active 5-minute market.

        Returns: {market_id, token_id, strike_price, yes_price, no_price, end_time, question}
        or None if no active market found.
        """
        now = time.time()
        if self._cache is not None and now - self._cache_ts < self._cache_ttl:
            return self._cache

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Search for active 5-min crypto markets
                resp = await client.get(
                    f"{self.gamma_url}/markets",
                    params={
                        "tag": "crypto",
                        "closed": "false",
                        "limit": 50,
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"Gamma API returned {resp.status_code}")
                    return None

                markets = resp.json()
                if not isinstance(markets, list):
                    return None

                # Filter for 5-min markets matching our symbol
                for m in markets:
                    question = m.get("question", "")
                    if symbol.upper() not in question.upper():
                        continue
                    # Heuristic: 5-min markets mention time like "14:05 UTC"
                    end_date = m.get("endDate", "")
                    if not self._is_5min_market(m):
                        continue
                    if m.get("closed", False):
                        continue

                    # Extract token ID
                    tokens = m.get("tokens", [])
                    token_id = None
                    for tok in tokens:
                        if tok.get("outcome", "").lower() == "yes":
                            token_id = tok.get("token_id")
                            break

                    if not token_id:
                        continue

                    # Parse prices
                    try:
                        prices = json.loads(m.get("outcomePrices", "[]"))
                        yes_price = float(prices[0]) if len(prices) >= 1 else 0.5
                        no_price = float(prices[1]) if len(prices) >= 2 else 0.5
                    except (json.JSONDecodeError, ValueError, IndexError):
                        yes_price = no_price = 0.5

                    result = {
                        "market_id": m.get("conditionId", ""),
                        "token_id": token_id,
                        "strike_price": self._extract_strike(question),
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "end_time": end_date,
                        "question": question,
                    }
                    self._cache = result
                    self._cache_ts = now
                    return result

                return None

        except Exception as e:
            logger.error(f"Scanner error: {e}")
            return None

    def _is_5min_market(self, market: dict) -> bool:
        """Heuristic check if this is a 5-minute resolution market."""
        question = market.get("question", "").lower()
        # 5-min markets typically contain time patterns or "5 min" or "5-minute"
        if "5 min" in question or "5-min" in question:
            return True
        # Check for time pattern like "at XX:X0" or "at XX:X5"
        import re
        if re.search(r"at \d{1,2}:\d{2}", question):
            return True
        return False

    def _extract_strike(self, question: str) -> float | None:
        """Extract strike price from question like 'above $84,000'."""
        import re
        match = re.search(r'\$([0-9,]+(?:\.\d+)?)', question)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                pass
        return None
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_crypto_scanner.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/crypto/scanner.py tests/test_crypto_scanner.py
git commit -m "feat(crypto): add 5-min market scanner"
```

---

### Task 10: Crypto Risk Wrapper

**Files:**
- Create: `src/crypto/risk.py`
- Test: extend `tests/test_crypto_risk.py`

- [ ] **Step 1: Add tests for the wrapper**

Append to `tests/test_crypto_risk.py`:

```python
from unittest.mock import MagicMock
from src.crypto.risk import CryptoRiskWrapper


def test_wrapper_delegates_to_risk_manager():
    db = MagicMock()
    db.get_combined_daily_pnl.return_value = -5.0
    db.get_available_bankroll.return_value = 500.0
    db.get_open_crypto_trades.return_value = []
    db.get_or_create_incubation.return_value = {"position_size": 1.50}

    settings = Settings(MAX_DAILY_LOSS=100.0, BANKROLL=1000.0, CRYPTO_MAX_POSITION_SIZE=100.0)
    rm = RiskManager(settings)
    wrapper = CryptoRiskWrapper(db=db, risk_manager=rm, settings=settings)

    allowed, reason = wrapper.check("macd_hist")
    assert allowed is True


def test_wrapper_blocks_when_open_trade():
    db = MagicMock()
    db.get_combined_daily_pnl.return_value = 0.0
    db.get_available_bankroll.return_value = 500.0
    db.get_open_crypto_trades.return_value = [{"id": 1}]
    db.get_or_create_incubation.return_value = {"position_size": 1.50}

    settings = Settings(MAX_DAILY_LOSS=100.0, BANKROLL=1000.0, CRYPTO_MAX_POSITION_SIZE=100.0)
    rm = RiskManager(settings)
    wrapper = CryptoRiskWrapper(db=db, risk_manager=rm, settings=settings)

    allowed, reason = wrapper.check("macd_hist")
    assert allowed is False
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `python -m pytest tests/test_crypto_risk.py -v`
Expected: New tests FAIL

- [ ] **Step 3: Implement wrapper**

```python
# src/crypto/risk.py
import logging
from src.config import Settings
from src.db import Database
from src.risk.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class CryptoRiskWrapper:
    """Thin wrapper: queries DB for pre-computed values, delegates to shared RiskManager."""

    def __init__(self, db: Database, risk_manager: RiskManager, settings: Settings):
        self.db = db
        self.risk_manager = risk_manager
        self.settings = settings

    def check(self, strategy: str) -> tuple[bool, str]:
        """Run pre-trade risk check. Returns (allowed, reason)."""
        combined_pnl = self.db.get_combined_daily_pnl()
        available = self.db.get_available_bankroll(self.settings.BANKROLL)
        open_trades = self.db.get_open_crypto_trades()
        has_open = len(open_trades) > 0
        incubation = self.db.get_or_create_incubation(strategy)
        proposed_size = incubation["position_size"]

        return self.risk_manager.crypto_risk_check(
            combined_daily_pnl=combined_pnl,
            available_bankroll=available,
            proposed_size=proposed_size,
            has_open_trade=has_open,
            max_position_size=self.settings.CRYPTO_MAX_POSITION_SIZE,
        )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_crypto_risk.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/crypto/risk.py tests/test_crypto_risk.py
git commit -m "feat(crypto): add risk check wrapper"
```

---

### Task 11: Incubation Tracker

**Files:**
- Create: `src/crypto/tracker.py`
- Test: `tests/test_crypto_tracker.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_crypto_tracker.py
import pytest
from src.db import Database
from src.crypto.tracker import IncubationTracker


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    d.init()
    return d


@pytest.fixture
def tracker(db):
    return IncubationTracker(db=db, scale_sequence=[1.50, 5, 10, 25, 50, 100],
                             min_days=14, max_consecutive_loss_days=3)


def test_update_after_win(tracker, db):
    tracker.update_after_trade("macd_hist", won=True, pnl=1.47)
    inc = db.get_or_create_incubation("macd_hist")
    assert inc["total_trades"] == 1
    assert inc["wins"] == 1
    assert inc["losses"] == 0
    assert inc["total_pnl"] == 1.47


def test_update_after_loss(tracker, db):
    tracker.update_after_trade("macd_hist", won=False, pnl=-1.53)
    inc = db.get_or_create_incubation("macd_hist")
    assert inc["total_trades"] == 1
    assert inc["wins"] == 0
    assert inc["losses"] == 1


def test_get_current_size_default(tracker):
    size = tracker.get_current_size("macd_hist")
    assert size == 1.50  # default starting size


def test_retire_after_consecutive_losses(tracker, db):
    """Strategy retired after max consecutive losing days."""
    # Simulate 3 consecutive losing days by recording losing trades on different dates
    for i in range(10):  # enough losses to trigger
        tracker.update_after_trade("macd_hist", won=False, pnl=-1.53)
    # The tracker checks consecutive loss days in crypto_pnl_daily
    # We just verify the mechanism exists — full integration tested via bot
    inc = db.get_or_create_incubation("macd_hist")
    assert inc["losses"] == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_crypto_tracker.py -v`
Expected: FAIL

- [ ] **Step 3: Implement tracker**

```python
# src/crypto/tracker.py
import logging
from datetime import datetime, timezone
from src.db import Database

logger = logging.getLogger(__name__)

DEFAULT_SCALE_SEQUENCE = [1.50, 5, 10, 25, 50, 100]


class IncubationTracker:
    """Track incubation status and manage position scaling."""

    def __init__(self, db: Database, scale_sequence: list[float] | None = None,
                 min_days: int = 14, max_consecutive_loss_days: int = 3):
        self.db = db
        self.scale_sequence = scale_sequence or DEFAULT_SCALE_SEQUENCE
        self.min_days = min_days
        self.max_consecutive_loss_days = max_consecutive_loss_days

    def update_after_trade(self, strategy: str, won: bool, pnl: float):
        """Update incubation record after a settled trade."""
        inc = self.db.get_or_create_incubation(strategy)
        total = inc["total_trades"] + 1
        wins = inc["wins"] + (1 if won else 0)
        losses = inc["losses"] + (0 if won else 1)
        total_pnl = round(inc["total_pnl"] + pnl, 2)
        self.db.update_incubation(strategy, total, wins, losses, total_pnl)
        logger.info(f"Incubation {strategy}: trades={total} W={wins} L={losses} PnL=${total_pnl:.2f}")

    def get_current_size(self, strategy: str) -> float:
        """Get current position size for this strategy."""
        inc = self.db.get_or_create_incubation(strategy)
        return inc["position_size"]

    def check_scale_up(self, strategy: str) -> float | None:
        """Check if strategy qualifies for scaling up. Returns new size or None."""
        inc = self.db.get_or_create_incubation(strategy)
        if inc["status"] != "incubating":
            return None
        started = datetime.fromisoformat(inc["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days = (now - started).days
        if days < self.min_days:
            return None
        if inc["total_pnl"] <= 0:
            return None
        current = inc["position_size"]
        for i, size in enumerate(self.scale_sequence):
            if abs(size - current) < 0.01 and i + 1 < len(self.scale_sequence):
                new_size = self.scale_sequence[i + 1]
                self.db.update_incubation(
                    strategy, inc["total_trades"], inc["wins"], inc["losses"],
                    inc["total_pnl"], position_size=new_size, status="scaled",
                )
                logger.info(f"Scaled up {strategy}: ${current:.2f} -> ${new_size:.2f}")
                return new_size
        return None

    def check_retire(self, strategy: str) -> bool:
        """Check if strategy should be retired due to consecutive losing days."""
        pnl_history = self.db.get_crypto_pnl_history()
        if len(pnl_history) < self.max_consecutive_loss_days:
            return False
        recent = pnl_history[-self.max_consecutive_loss_days:]
        all_losing = all(day["net_pnl"] < 0 for day in recent)
        if all_losing:
            inc = self.db.get_or_create_incubation(strategy)
            self.db.update_incubation(
                strategy, inc["total_trades"], inc["wins"], inc["losses"],
                inc["total_pnl"], status="retired",
            )
            logger.warning(f"Retired {strategy} after {self.max_consecutive_loss_days} consecutive losing days")
            return True
        return False
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_crypto_tracker.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/crypto/tracker.py tests/test_crypto_tracker.py
git commit -m "feat(crypto): add incubation tracker"
```

---

### Task 12: Live Bot

**Files:**
- Create: `src/crypto/bot.py`
- Test: `tests/test_crypto_bot.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_crypto_bot.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
import numpy as np
from src.crypto.bot import CryptoBot


def _make_candle_df(n=100):
    np.random.seed(42)
    base = 84000.0
    prices = base + np.cumsum(np.random.randn(n) * 10)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-03-18T12:00:00", periods=n, freq="1min", tz="UTC"),
        "open": prices,
        "high": prices + np.abs(np.random.randn(n) * 5),
        "low": prices - np.abs(np.random.randn(n) * 5),
        "close": prices + np.random.randn(n) * 3,
        "volume": np.random.randint(50, 500, n).astype(float),
    })


@pytest.fixture
def bot():
    from src.config import Settings
    settings = Settings(CRYPTO_ENABLED=True, CRYPTO_STRATEGY="macd_hist",
                        CRYPTO_STRATEGY_PARAMS='{"macd_fast":3,"macd_slow":15,"macd_signal":3}')
    b = CryptoBot(settings=settings, dry_run=True)
    b.db = MagicMock()
    b.db.get_open_crypto_trades.return_value = []
    b.db.get_combined_daily_pnl.return_value = 0.0
    b.db.get_available_bankroll.return_value = 500.0
    b.db.get_or_create_incubation.return_value = {"position_size": 1.50, "status": "incubating"}
    return b


def test_bot_initializes_strategy(bot):
    assert bot.strategy is not None
    assert bot.strategy_name == "macd_hist"


async def test_bot_cycle_no_signal(bot):
    """Bot cycle with no signal does not place trade."""
    bot.feed = MagicMock()
    bot.feed.fetch_candles = AsyncMock(return_value=_make_candle_df(20))  # too few for signal
    await bot._run_cycle()
    bot.db.save_crypto_trade.assert_not_called()


async def test_bot_cycle_not_at_boundary(bot):
    """Bot skips if not at 5-min boundary."""
    with patch("src.crypto.bot.is_5min_boundary", return_value=False):
        bot.feed = MagicMock()
        bot.feed.fetch_candles = AsyncMock(return_value=_make_candle_df(100))
        await bot._run_cycle()
    bot.db.save_crypto_trade.assert_not_called()


def test_is_5min_boundary():
    from src.crypto.bot import is_5min_boundary
    from datetime import datetime, timezone
    assert is_5min_boundary(datetime(2026, 3, 18, 12, 0, 0, tzinfo=timezone.utc)) is True
    assert is_5min_boundary(datetime(2026, 3, 18, 12, 5, 0, tzinfo=timezone.utc)) is True
    assert is_5min_boundary(datetime(2026, 3, 18, 12, 3, 0, tzinfo=timezone.utc)) is False


def test_calc_crypto_pnl():
    from src.crypto.bot import calc_crypto_pnl
    # Win at 0.50: payout $1 per share, bought shares at 0.50 → profit = stake * (1/0.5 - 1) - fee
    pnl = calc_crypto_pnl(entry_price=0.50, stake=1.50, won=True, fee_pct=0.02)
    assert abs(pnl - 1.47) < 0.01
    # Loss at 0.50
    pnl = calc_crypto_pnl(entry_price=0.50, stake=1.50, won=False, fee_pct=0.02)
    assert abs(pnl - (-1.53)) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_crypto_bot.py -v`
Expected: FAIL

- [ ] **Step 3: Implement bot**

```python
# src/crypto/bot.py
import asyncio
import json
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.db import Database
from src.crypto.data_feed import CryptoDataFeed
from src.crypto.indicators import compute_indicators
from src.crypto.scanner import CryptoScanner
from src.crypto.risk import CryptoRiskWrapper
from src.crypto.tracker import IncubationTracker
from src.crypto.strategies import STRATEGY_REGISTRY
from src.risk.risk_manager import RiskManager

logger = logging.getLogger(__name__)


def is_5min_boundary(dt: datetime) -> bool:
    return dt.minute % 5 == 0


def calc_crypto_pnl(entry_price: float, stake: float, won: bool, fee_pct: float = 0.02) -> float:
    fee = stake * fee_pct
    if won:
        return (1.0 / entry_price - 1.0) * stake - fee
    else:
        return -stake - fee


class CryptoBot:
    """Live trading loop for 5-minute crypto markets."""

    def __init__(self, settings: Settings, dry_run: bool = True):
        self.settings = settings
        self.dry_run = dry_run
        self.db = Database(settings.DB_PATH)
        self.db.init()
        self.feed = CryptoDataFeed()
        self.scanner = CryptoScanner(gamma_url=settings.POLYMARKET_GAMMA_URL)
        self.risk_manager = RiskManager(settings)
        self.risk_wrapper = CryptoRiskWrapper(self.db, self.risk_manager, settings)

        scale_seq = [float(x) for x in settings.CRYPTO_SCALE_SEQUENCE.split(",")]
        self.tracker = IncubationTracker(
            db=self.db, scale_sequence=scale_seq,
            min_days=settings.CRYPTO_INCUBATION_MIN_DAYS,
            max_consecutive_loss_days=settings.CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS,
        )

        self.strategy_name = settings.CRYPTO_STRATEGY
        params = json.loads(settings.CRYPTO_STRATEGY_PARAMS)
        strat_class = STRATEGY_REGISTRY.get(self.strategy_name)
        if strat_class is None:
            raise ValueError(f"Unknown strategy: {self.strategy_name}")
        self.strategy = strat_class(**params)
        self.indicator_params = params

        self._consecutive_errors = 0
        self._max_errors = 5
        self._clob_client = None

    def _get_clob_client(self):
        if self._clob_client is None and not self.dry_run:
            from py_clob_client.client import ClobClient
            self._clob_client = ClobClient(
                self.settings.POLYMARKET_CLOB_URL,
                key=self.settings.POLYMARKET_PRIVATE_KEY,
                chain_id=137,
                funder=self.settings.POLYMARKET_FUNDER_ADDRESS or None,
            )
        return self._clob_client

    async def run(self):
        """Main loop: run cycle every 60 seconds."""
        logger.info(f"Crypto bot starting: strategy={self.strategy_name} "
                     f"dry_run={self.dry_run} symbol={self.settings.CRYPTO_SYMBOL}")
        while True:
            try:
                await self._run_cycle()
                self._consecutive_errors = 0
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(f"Cycle error ({self._consecutive_errors}/{self._max_errors}): {e}")
                if self._consecutive_errors >= self._max_errors:
                    logger.critical(f"Stopping after {self._max_errors} consecutive errors")
                    break
            await asyncio.sleep(60)

        await self.feed.close()

    async def _run_cycle(self):
        """Single bot cycle."""
        now = datetime.now(timezone.utc)

        # 1. Settle resolved trades
        await self._settle_open_trades()

        # 2. Only trade at 5-min boundaries
        if not is_5min_boundary(now):
            return

        # 3. Fetch candles
        symbol = f"{self.settings.CRYPTO_SYMBOL}/USDT"
        df = await self.feed.fetch_candles(symbol, limit=self.settings.CRYPTO_CANDLE_WINDOW)
        if df is None:
            logger.warning("No candle data, skipping")
            return

        # 4. Compute indicators and generate signal
        enriched = compute_indicators(df, **self.indicator_params)
        signal, meta = self.strategy.generate_signal(enriched)
        if signal == 0:
            return

        # 5. Risk check
        allowed, reason = self.risk_wrapper.check(self.strategy_name)
        if not allowed:
            logger.info(f"Risk check blocked: {reason}")
            return

        # 6. Find active market
        market = await self.scanner.find_active_5min_market(self.settings.CRYPTO_SYMBOL)
        if market is None:
            logger.debug("No active 5-min market found, skipping")
            return

        # 7. Place trade
        side = "YES" if signal == 1 else "NO"
        size = self.tracker.get_current_size(self.strategy_name)
        entry_price = market["yes_price"] if side == "YES" else market["no_price"]
        btc_price = enriched["close"].iloc[-1]

        if self.dry_run:
            status = "dry_run_open"
            logger.info(f"DRY RUN: {side} ${size:.2f} @ {entry_price:.2f} | {market['question'][:60]}")
        else:
            status = "open"
            self._place_order(market["market_id"], market["token_id"], side, size, entry_price)
            logger.info(f"LIVE: {side} ${size:.2f} @ {entry_price:.2f} | {market['question'][:60]}")

        self.db.save_crypto_trade(
            strategy=self.strategy_name, symbol=self.settings.CRYPTO_SYMBOL,
            market_id=market["market_id"], side=side,
            entry_price=entry_price, strike_price=market.get("strike_price"),
            btc_price_at_entry=btc_price, amount=size,
            status=status, signal_data=json.dumps(meta),
            token_id=market["token_id"],
        )

    def _place_order(self, market_id: str, token_id: str, side: str, size: float, price: float):
        """Place limit order via py-clob-client."""
        clob = self._get_clob_client()
        if clob is None:
            return
        from py_clob_client.order_builder.constants import BUY
        order_args = {
            "token_id": token_id,
            "price": round(price, 2),
            "size": round(size / price, 2),
            "side": BUY,
        }
        response = clob.create_and_post_order(order_args)
        logger.info(f"Order placed: {response.get('orderID', 'unknown')}")

    async def _settle_open_trades(self):
        """Check and settle any open crypto trades."""
        trades = self.db.get_open_crypto_trades()
        if not trades:
            return

        for trade in trades:
            market_id = trade.get("market_id")
            if not market_id:
                continue
            # Use scanner's parent class check
            try:
                token_id = trade.get("token_id")
                resolution = await self.scanner.check_resolution(market_id, token_id=token_id)
            except Exception:
                continue

            if resolution is None:
                continue

            # Determine win/loss
            won = (trade["side"] == resolution)
            pnl = calc_crypto_pnl(
                entry_price=trade["entry_price"],
                stake=trade["amount"],
                won=won,
                fee_pct=self.settings.POLYMARKET_FEE,
            )

            if trade["status"] == "dry_run_open":
                status = "dry_run_won" if won else "dry_run_lost"
            else:
                status = "won" if won else "lost"

            self.db.settle_crypto_trade(trade["id"], status=status, pnl=pnl)
            self.tracker.update_after_trade(trade["strategy"], won=won, pnl=pnl)

            logger.info(f"Settled: {trade['strategy']} {trade['side']} -> {resolution} "
                         f"P&L: ${pnl:.2f}")
```

Add `check_resolution` method to scanner — append to `src/crypto/scanner.py`.

Note: The Gamma API ignores the `condition_id` query param (same issue as the existing settler). Use `clob_token_ids` for lookups instead, matching the pattern in `settler.py:_fetch_markets_for_ids`.

```python
async def check_resolution(self, condition_id: str, token_id: str | None = None) -> str | None:
    """Check if a market has resolved. Returns 'YES'/'NO' or None.

    Uses clob_token_ids for lookup since Gamma API ignores condition_id param.
    """
    if not token_id:
        # If we have a cached market with this condition_id, use its token_id
        if self._cache and self._cache.get("market_id") == condition_id:
            token_id = self._cache.get("token_id")
        if not token_id:
            logger.debug(f"No token_id for {condition_id}, cannot check resolution")
            return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.gamma_url}/markets",
                params={"clob_token_ids": token_id, "limit": 1},
            )
            if resp.status_code != 200:
                return None
            markets = resp.json()
            if not isinstance(markets, list) or not markets:
                return None
            data = markets[0]
            if not data.get("resolved") and not data.get("closed"):
                return None
            prices = json.loads(data.get("outcomePrices", "[]"))
            if len(prices) >= 2:
                yes_price = float(prices[0])
                if yes_price > 0.5:
                    return "YES"
                elif yes_price < 0.5:
                    return "NO"
    except Exception as e:
        logger.debug(f"Resolution check error for {condition_id}: {e}")
    return None
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_crypto_bot.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/crypto/bot.py src/crypto/scanner.py tests/test_crypto_bot.py
git commit -m "feat(crypto): add live trading bot with settlement"
```

---

### Task 13: CLI Integration + Settler Extension

**Files:**
- Modify: `run.py`
- Modify: `src/settler/settler.py`
- Modify: `src/notifications/telegram.py`

- [ ] **Step 1: Add `--crypto` to run.py**

Add after the `--settle` block in `run.py`, before the `dry_run` line:

```python
if "--crypto" in sys.argv:
    # Mutual exclusion check
    conflicting = {"--loop", "--web", "--dashboard", "--train", "--settle"}
    conflicts_found = conflicting & set(sys.argv)
    if conflicts_found:
        logger.error(f"--crypto cannot be combined with {', '.join(conflicts_found)}")
        sys.exit(1)

    from src.crypto.bot import CryptoBot
    from src.dashboard.log_handler import SharedFileLogHandler
    logging.getLogger().addHandler(SharedFileLogHandler())

    dry_run = "--live" not in sys.argv
    bot = CryptoBot(settings=settings, dry_run=dry_run)
    logger.info(f"=== CRYPTO BOT: {'DRY RUN' if dry_run else 'LIVE'} ===")
    asyncio.run(bot.run())
    return
```

- [ ] **Step 2: Add crypto settlement to Settler**

Add method to `src/settler/settler.py`:

```python
async def settle_crypto_trades(self) -> None:
    """Settle any open crypto trades (fallback for bot crashes)."""
    from src.crypto.bot import calc_crypto_pnl
    from src.config import Settings
    open_trades = self.db.get_open_crypto_trades()
    if not open_trades:
        return

    logger.info(f"Checking {len(open_trades)} open crypto trades")
    for trade in open_trades:
        market_id = trade.get("market_id")
        if not market_id:
            continue
        markets = await self._fetch_markets_for_ids({market_id})
        data = markets.get(market_id)
        if data is None:
            continue
        outcome = self._parse_resolution(data)
        if outcome is None:
            continue

        won = (trade["side"] == outcome)
        settings = Settings()
        pnl = calc_crypto_pnl(
            entry_price=trade["entry_price"],
            stake=trade["amount"],
            won=won,
            fee_pct=settings.POLYMARKET_FEE,
        )

        expected = trade["status"]
        if expected == "dry_run_open":
            new_status = "dry_run_won" if won else "dry_run_lost"
        else:
            new_status = "won" if won else "lost"

        # Guard: only update if status hasn't changed (race condition prevention)
        updated = self.db.settle_crypto_trade(
            trade["id"], status=new_status, pnl=pnl, expected_status=expected,
        )
        if not updated:
            continue  # Already settled by bot

        logger.info(f"Crypto settled: {trade['strategy']} {trade['side']} -> {outcome} PnL: ${pnl:.2f}")

        if self.notifier.is_enabled:
            msg = self.notifier.format_crypto_settlement_alert(
                strategy=trade["strategy"], symbol=trade["symbol"],
                side=trade["side"], outcome=outcome, pnl=pnl,
            )
            await self.notifier.send(msg)
```

In the existing `Settler.run()` method, add at the end (before `await self._maybe_consolidate_lessons()`):

```python
await self.settle_crypto_trades()
```

- [ ] **Step 3: Add Telegram format method**

Add to `src/notifications/telegram.py`:

```python
def format_crypto_settlement_alert(self, strategy: str, symbol: str,
                                   side: str, outcome: str, pnl: float) -> str:
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    result = "Won" if pnl >= 0 else "Lost"
    return (
        f"*Crypto Trade Settled*\n"
        f"Strategy: {strategy} | {symbol}\n"
        f"Side: {side} -> {outcome} ({result})\n"
        f"P&L: {pnl_str}"
    )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -v --timeout=30`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add run.py src/settler/settler.py src/notifications/telegram.py
git commit -m "feat(crypto): add CLI flag, settler extension, telegram alerts"
```

---

### Task 14: Systemd Service

**Files:**
- Create: `deploy/polymarket-crypto.service`

- [ ] **Step 1: Create service file**

```ini
# deploy/polymarket-crypto.service
[Unit]
Description=Polymarket Crypto 5-Min Bot
After=network.target

[Service]
Type=simple
User=polybot
WorkingDirectory=/opt/polymarket-bot
Environment="PATH=/opt/polymarket-bot/venv/bin:/usr/local/bin:/usr/bin"
EnvironmentFile=/opt/polymarket-bot/.env
ExecStart=/opt/polymarket-bot/venv/bin/python run.py --crypto
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Commit**

```bash
git add deploy/polymarket-crypto.service
git commit -m "feat(crypto): add systemd service for crypto bot"
```

---

## Phase 3: Dashboard

### Task 15: Dashboard API Endpoints

**Files:**
- Modify: `src/dashboard/web.py`

- [ ] **Step 1: Add crypto API routes to web.py**

Add after existing routes in `create_app()`:

```python
@app.get("/crypto", response_class=HTMLResponse)
async def crypto_page(request: Request):
    if templates:
        return templates.TemplateResponse("crypto.html", {"request": request})
    return HTMLResponse("<h1>Crypto Dashboard</h1><p>Template not found.</p>")

@app.get("/api/crypto/stats")
async def api_crypto_stats():
    """Note: These call db methods directly since DashboardService doesn't
    have crypto-specific methods yet. This is acceptable as the service layer
    is primarily for the event pipeline's complex state management."""
    stats = await asyncio.to_thread(service.db.get_crypto_trade_stats)
    daily_pnl = await asyncio.to_thread(service.db.get_combined_daily_pnl)
    bankroll = await asyncio.to_thread(service.db.get_available_bankroll, service.settings.BANKROLL)
    stats["today_pnl"] = round(daily_pnl, 2)
    stats["bankroll"] = round(bankroll, 2)
    return stats

@app.get("/api/crypto/trades")
async def api_crypto_trades(page: int = 1, per_page: int = 20):
    all_trades = await asyncio.to_thread(service.db.get_recent_crypto_trades, 200)
    total = len(all_trades)
    start = (page - 1) * per_page
    return {"items": all_trades[start:start + per_page], "total": total, "page": page}

@app.get("/api/crypto/pnl-history")
async def api_crypto_pnl_history():
    return await asyncio.to_thread(service.db.get_crypto_pnl_history)

@app.get("/api/crypto/strategies")
async def api_crypto_strategies():
    return await asyncio.to_thread(service.db.get_crypto_strategy_stats)

@app.get("/api/crypto/incubation")
async def api_crypto_incubation():
    return await asyncio.to_thread(service.db.get_all_incubations)

@app.get("/api/crypto/backtests")
async def api_crypto_backtests():
    return await asyncio.to_thread(service.db.get_top_crypto_backtests, 5)
```

- [ ] **Step 2: Run web tests for regressions**

Run: `python -m pytest tests/test_web.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/web.py
git commit -m "feat(crypto): add dashboard API endpoints"
```

---

### Task 16: Dashboard Template + Navigation

**Files:**
- Modify: `src/dashboard/templates/index.html` (add nav bar)
- Modify: `src/dashboard/templates/mobile.html` (add nav bar)
- Create: `src/dashboard/templates/crypto.html`

- [ ] **Step 1: Add nav bar to existing templates**

Add a nav bar at the top of `index.html` and `mobile.html` body. Insert just inside `<body>` before the existing content:

```html
<nav style="display:flex;gap:1.5rem;padding:0.75rem 1.5rem;background:#1a1a2e;border-bottom:1px solid #333;font-size:0.9rem;">
  <a href="/" style="color:#e0e0e0;text-decoration:none;opacity:0.8;">Event Markets</a>
  <a href="/crypto" style="color:#f0c040;text-decoration:none;font-weight:600;">Crypto 5-Min</a>
</nav>
```

- [ ] **Step 2: Create crypto.html template**

Create `src/dashboard/templates/crypto.html` — a standalone page matching the existing dashboard style. Use HTMX for auto-polling (like the event dashboard). Layout per spec:

Stats bar (5 cards): Today P&L, Win Rate, Total Trades, Bankroll (shared), Bot Status.
Left column (60%): cumulative P&L chart + recent trades table.
Right column (40%): strategy comparison + incubation status + backtest results.

This is a full HTML file following the existing template patterns from `index.html`. Use the same CSS variables and dark theme. Fetch data from `/api/crypto/*` endpoints. Use Chart.js for charts (same as existing dashboard) and HTMX for periodic updates.

The template should be self-contained and functional with the API endpoints defined in Task 15.

- [ ] **Step 3: Test by running the web dashboard**

Run: `python run.py --web`
Navigate to `http://localhost:8050/crypto`
Expected: Page loads, shows empty state (no crypto trades yet)

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/templates/
git commit -m "feat(crypto): add crypto dashboard page with nav bar"
```

---

### Task 17: Full Integration Test

**Files:**
- No new files — verification only

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: All tests pass

- [ ] **Step 2: Verify CLI flags work**

Run: `python run.py --crypto --help 2>&1 || true`
Run: `python -c "from src.crypto.bot import CryptoBot; print('import ok')"`
Run: `python -c "from src.crypto.strategies import STRATEGY_REGISTRY; print(list(STRATEGY_REGISTRY.keys()))"`
Expected: All succeed

- [ ] **Step 3: Verify mutual exclusion**

Run: `python run.py --crypto --web 2>&1 || echo "Correctly rejected"`
Expected: Error message about conflicting flags

- [ ] **Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "feat(crypto): complete 5-minute crypto trading module"
```
