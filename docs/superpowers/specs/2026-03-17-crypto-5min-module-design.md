# Design: 5-Minute Crypto Trading Module

## Overview

Add a 5-minute crypto resolution market trader to the existing Polymarket bot. The module uses **zero Claude API calls** — all signals come from pandas-ta technical indicators. It shares the same Polymarket account, bankroll, database, risk limits, and dashboard as the existing event market bot.

## Architecture: Fully Integrated (Approach A)

The crypto module lives at `src/crypto/` but deeply shares infrastructure: same `Database` class (extended), same `RiskManager` (extended), same `Settler` (extended), same FastAPI dashboard (new routes).

## Module Structure

```
src/crypto/
├── __init__.py
├── config.py           # CryptoSettings (Pydantic, loaded from .env)
├── scanner.py          # Find active 5-min BTC/ETH markets on Polymarket
├── data_feed.py        # Fetch 1m candles from Coinbase via ccxt
├── indicators.py       # pandas-ta indicator computation
├── strategies/
│   ├── __init__.py
│   ├── base.py         # CryptoStrategy ABC
│   ├── macd_hist.py    # MACD histogram crossover
│   ├── rsi_bb.py       # RSI + Bollinger Band squeeze
│   ├── vwap_cap.py     # VWAP capitulation reversion
│   └── ema_cross.py    # EMA crossover (fast/slow)
├── backtester/
│   ├── __init__.py
│   ├── engine.py       # Single strategy backtest
│   └── runner.py       # Multi-strategy x param grid runner
├── bot.py              # Live trading loop
├── risk.py             # Thin wrapper — delegates to shared RiskManager
└── tracker.py          # Incubation tracking (scale up/down over time)
```

## Data Flow

### Live Bot Loop (every 60s)

```
ccxt (Coinbase) -> 100 x 1m candles
  -> indicators.py (pandas-ta)
  -> strategy.generate_signal()
  -> if signal != 0 AND at 5-min boundary:
      -> crypto/risk.py -> shared RiskManager.crypto_risk_check()
      -> crypto/scanner.py -> find active 5-min Polymarket market
      -> crypto/bot.py places order directly via py-clob-client
      -> save to crypto_trades table
      -> bot settles resolved trades inline
```

### Backtester (offline)

```
crypto_candles table or CSV -> indicators -> strategy.backtest_signal()
  -> engine scores results -> runner compares grid -> saves to crypto_backtests
```

## Integration Points (Existing Files Modified)

| File | Change |
|------|--------|
| `src/db.py` | Add 5 crypto tables in `init()`, add crypto query methods |
| `src/risk/risk_manager.py` | Add `crypto_risk_check()` method (receives pre-computed values, not db) |
| `src/settler/settler.py` | Add `settle_crypto_trades()` called in existing `run()` |
| `src/dashboard/web.py` | Add `/crypto` route + crypto API endpoints |
| `src/dashboard/templates/` | New `crypto.html` template, nav bar on existing templates |
| `src/config.py` | Add crypto settings to existing `Settings` class |
| `run.py` | Add `--crypto` CLI flag |
| `pyproject.toml` | Add `pandas-ta`, `ccxt` dependencies |

## Database Schema

### 5 New Tables (added to existing `db.py` init)

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
    params TEXT NOT NULL,             -- JSON of param combo tested
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
    side TEXT NOT NULL,               -- 'YES' (long/above strike) or 'NO' (short/below strike)
    entry_price REAL NOT NULL,        -- price paid on Polymarket (0-1)
    strike_price REAL,
    btc_price_at_entry REAL,
    amount REAL NOT NULL,
    status TEXT DEFAULT 'open',       -- open -> won -> lost (dry_run_open -> dry_run_won -> dry_run_lost in dry-run mode)
    pnl REAL,
    signal_data TEXT,                 -- JSON: indicator values
    placed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME
);

CREATE TABLE IF NOT EXISTS crypto_incubation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    position_size REAL DEFAULT 1.50,
    total_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0.0,
    status TEXT DEFAULT 'incubating', -- incubating -> scaled -> retired
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

### Shared Bankroll

```
available = BANKROLL
          - SUM(amount) FROM trades WHERE status IN ('dry_run', 'pending')
          - SUM(amount) FROM crypto_trades WHERE status = 'open'
```

New `get_available_bankroll()` method on `Database`.

### Combined Daily P&L

```
combined_daily_pnl = SUM(COALESCE(pnl, hypothetical_pnl)) FROM trades WHERE settled today
                   + SUM(pnl) FROM crypto_trades WHERE resolved today
```

New `get_combined_daily_pnl()` method on `Database`. Uses net P&L (not just losses) to match the existing `get_daily_pnl()` methodology. The shared `MAX_DAILY_LOSS` ($100) applies: if `combined_daily_pnl <= -MAX_DAILY_LOSS`, both modules stop trading.

## Strategies

### Base Class

`CryptoStrategy` ABC with two methods:
- `generate_signal(df) -> (int, dict)` — Returns signal (1=YES/long, -1=NO/short, 0=no trade) plus metadata dict
- `backtest_signal(df) -> list[dict]` — Walks full DataFrame, generates signals at 5-min boundaries, returns trade log

### Four Strategies

**MACD Histogram Crossover** — Signal when MACD histogram crosses zero. Params: `macd_fast`, `macd_slow`, `macd_signal`.

**RSI + Bollinger Band Squeeze** — Signal when RSI oversold/overbought AND BB bandwidth below squeeze threshold. Params: `rsi_length`, `bb_length`, `bb_std`, `rsi_oversold`, `rsi_overbought`, `squeeze_threshold`.

**VWAP Capitulation Reversion** — Signal when price drops below VWAP with volume spike. Params: `vol_spike_min`, `vwap_revert_pct`, `vol_sma_length`.

**EMA Crossover** — Signal when fast EMA crosses slow EMA. Params: `ema_fast`, `ema_slow`.

### Indicators (pandas-ta)

All computed in `indicators.py` on a 1m candle DataFrame:
- MACD (configurable fast/slow/signal)
- RSI (configurable length)
- Bollinger Bands (configurable length/std) + bandwidth
- VWAP
- EMA pair (configurable fast/slow)
- Volume SMA + volume spike ratio
- ATR (14-period, for volatility context)

### Parameter Grid

```python
PARAM_GRID = {
    'macd_hist': [
        {'macd_fast': 3, 'macd_slow': 15, 'macd_signal': 3},
        {'macd_fast': 8, 'macd_slow': 21, 'macd_signal': 5},
        {'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9},
    ],
    'rsi_bb': [
        {'rsi_length': 7, 'bb_length': 20, 'bb_std': 2.0, 'rsi_oversold': 30, 'rsi_overbought': 70, 'squeeze_threshold': 0.02},
        {'rsi_length': 14, 'bb_length': 20, 'bb_std': 2.0, 'rsi_oversold': 25, 'rsi_overbought': 75, 'squeeze_threshold': 0.015},
    ],
    'vwap_cap': [
        {'vol_spike_min': 2.0, 'vwap_revert_pct': 0.001, 'vol_sma_length': 20},
        {'vol_spike_min': 3.0, 'vwap_revert_pct': 0.0005, 'vol_sma_length': 20},
    ],
    'ema_cross': [
        {'ema_fast': 5, 'ema_slow': 13},
        {'ema_fast': 8, 'ema_slow': 21},
        {'ema_fast': 3, 'ema_slow': 10},
    ],
}
```

## Backtesting

### Engine

Simulates Polymarket 5-min markets:
- At each 5-min boundary in historical data, check for signal
- If signal, simulate entry at configurable Polymarket price (default 0.50)
- At next 5-min mark, check if BTC moved in predicted direction
- Win: `(1/entry_price - 1) * stake - fee`, Loss: `-stake - fee`
- Fee model: 2% taker fee

Output metrics: total trades, win rate, expectancy, total P&L, max drawdown, profit factor, Sharpe ratio.

### Runner

Executes all strategies x all param combos from PARAM_GRID sequentially (SQLite doesn't love concurrent writes). Sorts by expectancy. Saves to `crypto_backtests` table.

## Live Bot

### Main Loop (every 60s)

1. Fetch latest 100 x 1m candles from Coinbase via ccxt (free, no API key)
2. Compute all indicators
3. Check if at 5-min boundary (XX:00, XX:05, etc.)
4. If at boundary AND no open crypto trade for this window:
   - Generate signal
   - If signal != 0, run `crypto_risk_check()`
   - If approved, find active 5-min market via `scanner.find_active_5min_market()`
   - Place limit order via shared executor
   - Save to `crypto_trades` with signal metadata
5. Check for resolved trades inline — settle if resolved
6. On error: log, continue. After 5 consecutive errors, stop.

Entry: `python run.py --crypto` or `python -m src.crypto.bot`.

## Order Execution

The crypto module does NOT use the existing `TradeExecutor` — that class is tightly coupled to event-market `TradeDecision`/`Prediction` Pydantic models. Instead, `bot.py` places orders directly using the shared `py-clob-client` instance:

```python
# In bot.py
def place_trade(self, market_id: str, token_id: str, side: str, size: float, price: float):
    """
    Place limit order on Polymarket CLOB.
    side: 'YES' or 'NO'
    size: USDC amount to wager
    price: limit price (0-1)

    Uses the same py-clob-client as the event bot (shared CLOB credentials).
    Saves to crypto_trades table (not the event trades table).
    """
```

The CLOB client is initialized from `POLYMARKET_PRIVATE_KEY` (same as event bot). In dry-run mode, the order is skipped and the trade is saved with status `dry_run_open`.

## Dry-Run Mode

The crypto bot supports dry-run mode (default) matching the event bot pattern:
- `python run.py --crypto` — dry-run (no real orders, saves as `dry_run_open`)
- `python run.py --crypto --live` — real orders (saves as `open`)
- Status flow: `dry_run_open -> dry_run_won / dry_run_lost` or `open -> won / lost`
- Shared bankroll query includes both: `status IN ('open', 'dry_run_open')`

## Market Scanner

### How 5-Minute Crypto Markets Work on Polymarket

Polymarket hosts 5-minute resolution markets for BTC/ETH with questions like "Will BTC be above $X at 14:05 UTC?" where X is the strike price. These are created programmatically and resolve every 5 minutes.

### Scanner Discovery (`src/crypto/scanner.py`)

```python
async def find_active_5min_market(self, symbol: str = "BTC") -> dict | None:
    """
    Query Polymarket Gamma API for the current active 5-minute market.

    Discovery method:
    1. GET /markets with tag filter for crypto 5-min markets
    2. Filter by: not yet resolved, end_date within next 5 minutes
    3. Match symbol (BTC/ETH)

    Returns: {market_id, token_id, strike_price, yes_price, no_price, end_time}
    or None if no active market found.

    If no market found, the bot skips this 5-min window (no trade).
    Markets may not always be available — this is expected and not an error.
    """
```

The scanner caches the Gamma API response for 60s to avoid redundant calls. If no 5-min market exists for a given window, the bot simply skips — this is a normal condition, not an error.

## Risk Integration

### New method on existing `RiskManager`

**`crypto_risk_check(combined_daily_pnl, available_bankroll, proposed_size, has_open_trade)`** returns `(allowed: bool, reason: str)`.

All values are pre-computed by the caller (matching existing pattern where `evaluate()` receives `daily_pnl` as a float, not a db reference):

1. `combined_daily_pnl > -MAX_DAILY_LOSS`
2. `proposed_size` <= incubation position size for this strategy
3. `available_bankroll` >= 2 * proposed_size
4. `has_open_trade` is False (max 1 concurrent crypto trade)

### Crypto Risk Wrapper (`src/crypto/risk.py`)

Thin layer that queries DB for pre-computed values (combined daily pnl, available bankroll, open trade count, incubation size) and delegates to shared risk manager.

## Settlement

### Two Paths

**Inline (primary):** Bot checks open crypto trades every 60s. 5-min markets resolve quickly, so most settle within minutes.

**Settler fallback:** Extend `Settler.run()` to call `settle_crypto_trades()` after event settlement. Uses the same Gamma API `check_resolution()` method (5-min markets resolve via Polymarket's standard resolution mechanism). Catches trades missed if bot crashed. Updates `crypto_trades`, `crypto_incubation`, `crypto_pnl_daily`. Sends Telegram notification via new `format_crypto_settlement_alert()` on `TelegramNotifier`.

**Race condition prevention:** Both the bot and settler may try to settle the same trade. The DB update uses `WHERE status = 'open'` (or `dry_run_open`) as a guard — if the status already changed, the second settler silently skips it. No locking needed.

## Incubation Tracker

After each settled crypto trade, `tracker.py` updates `crypto_incubation`:
- Increment wins/losses/total_trades, update total_pnl
- After `CRYPTO_INCUBATION_MIN_DAYS` (14 days), if profitable, advance to next size in scale sequence (1.50 -> 5 -> 10 -> 25 -> 50 -> 100)
- If strategy hits `CRYPTO_MAX_CONSECUTIVE_LOSS_DAYS` (default 3, configurable) consecutive losing days, pause it (status -> `retired`)

## Dashboard Extension

### Navigation

Add nav bar to existing templates (`index.html`, `mobile.html`) with two links: Event Markets (/) and Crypto 5-Min (/crypto).

### New Routes

| Endpoint | Returns |
|----------|---------|
| `GET /crypto` | Serves `crypto.html` template |
| `GET /api/crypto/stats` | Today P&L, win rate, total trades, shared bankroll, bot status |
| `GET /api/crypto/trades` | Recent crypto trades (paginated) |
| `GET /api/crypto/pnl-history` | Daily P&L series for charting |
| `GET /api/crypto/strategies` | Per-strategy win rate and P&L |
| `GET /api/crypto/incubation` | Incubation status table |
| `GET /api/crypto/backtests` | Top 5 backtest configs by expectancy |

### Layout

Stats bar (5 cards) at top: Today P&L, Win Rate, Total Trades, Bankroll (shared), Bot Status. Left column (60%): cumulative P&L chart + recent trades table. Right column (40%): strategy comparison bar chart + incubation status + backtest results.

Both pages show shared bankroll via `db.get_available_bankroll()`.

## Configuration

Added to existing `Settings` class in `src/config.py`:

```python
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

`CRYPTO_STRATEGY_PARAMS` is validated at startup via a Pydantic field validator that parses the JSON string and checks for required keys based on the selected strategy.

## Dependencies

Add to `pyproject.toml`:
- `pandas-ta` — technical indicators (free, no API)
- `ccxt` — exchange data (Coinbase public API, no key needed)

## Deployment

New systemd service `polymarket-crypto.service`. Cron for daily candle download.

## Implementation Order

### Phase 1: Data + Backtesting
1. Database migrations (5 new tables)
2. Data feed (download 90 days 1m BTC candles via ccxt)
3. Indicators (pandas-ta computation)
4. Strategy base class
5. First strategy (macd_hist)
6. Backtest engine
7. Remaining strategies (rsi_bb, vwap_cap, ema_cross)
8. Backtest runner (grid sweep, comparison, save to DB)
9. Run full backtest grid

### Phase 2: Live Bot
10. Risk manager extension
11. Crypto bot (live loop, market lookup, order placement)
12. Settler extension
13. Incubation tracker
14. Systemd service
15. Deploy best strategy at $1.50

### Phase 3: Dashboard
16. Dashboard routing (nav bar)
17. Crypto dashboard page (stats, P&L chart, trades table)
18. Strategy comparison + incubation status
19. Shared bankroll display
20. Backtest results panel

## SQLite Concurrency

The crypto bot runs as a separate systemd service writing to the same SQLite file as the event bot and settler. WAL mode + `busy_timeout=30000` (already configured) handles this. Both processes call `db.init()` at startup — `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE` migrations are idempotent and safe to run concurrently. Shared bankroll queries may see briefly stale data due to WAL checkpointing, but this is acceptable for risk checks (worst case: a trade is approved with slightly stale bankroll, off by one position's worth).

## `crypto_pnl_daily` Population

Updated by the settler's `settle_crypto_trades()` method after each batch of settlements. For each resolved trade, the settler upserts today's row in `crypto_pnl_daily` (INSERT OR REPLACE keyed on date). The `cumulative_pnl` and `bankroll_after` fields are recomputed from the full history on each upsert. The bot's inline settlement also updates this table via the same codepath.

## CLI Integration (`run.py`)

`--crypto` is a standalone mode flag, like `--web` or `--settle`:
- `python run.py --crypto` — dry-run crypto bot
- `python run.py --crypto --live` — live crypto bot
- Cannot combine with `--loop` (that runs the event pipeline), `--dashboard`, `--web`, `--train`, or `--settle`
- The crypto bot has its own internal 60s loop; no `--interval` flag needed

## Backtest Entry Price Limitation

The backtester uses a configurable default entry price of 0.50 (fair odds). Real 5-minute markets may trade at varying prices. This is a known simplification — backtest results represent theoretical performance. The `entry_price` parameter can be adjusted (e.g., 0.55 to simulate unfavorable pricing) to stress-test strategies.

## Implementation Notes

These items should be resolved during implementation:
- Verify exact event trade status values used for open/unresolved trades when building the shared bankroll query
- Add mutual exclusion check in `run.py` so `--crypto` cannot combine with `--loop`/`--web`/etc. (explicit error message)
- Ensure scanner returns `token_id` and it flows through to `place_trade()` for py-clob-client
- Set minimum candle count threshold (e.g., 60) before computing indicators — skip if ccxt returns insufficient data
- Reference `POLYMARKET_FEE` from config in backtester rather than hardcoding 2%
- Track consecutive losing days either via `crypto_incubation.consecutive_loss_days` column or by querying `crypto_trades` history

## Key Constraints

- Zero Claude API spend — all signals from pandas-ta only
- Shared bankroll — both bots draw from same Polymarket account
- Shared daily loss limit — $100 MAX_DAILY_LOSS is combined across both modules
- Same droplet, same venv, same SQLite DB, same dashboard
- Backtest first — no live deployment until winning config identified
- $1.50 starting position, scale only after 2+ weeks profitable
- Limit orders only
- Bot stops after 5 consecutive errors
