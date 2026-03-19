# Edge-Based Position Exit System

**Date:** 2026-03-19
**Status:** Approved

## Problem

The bot currently holds all positions to resolution. Positions where the edge has evaporated, losses are mounting, or capital is stale sit locked up indefinitely. This prevents capital redeployment and exposes the bankroll to unnecessary drawdown.

## Solution

Add an exit evaluation step to the settler's hourly cycle. After refreshing current prices, evaluate each open position against four exit rules. Conservative thresholds are configurable via `.env` and designed to be tightened as model accuracy improves.

## Exit Rules (checked in priority order)

For each open position, the first rule that triggers wins:

| Priority | Rule | Condition | Rationale |
|---|---|---|---|
| 1 | **Stop loss** | unrealised PnL < -40% of amount wagered | Cut losses before full wipeout |
| 2 | **Edge gone negative** | current edge < -5% (round-trip fees) | Market moved past prediction — edge is gone |
| 3 | **Big winner lock-in** | unrealised PnL > 60% of max possible profit | Lock in gains when most value is captured |
| 4 | **Stale position** | open > 30 days AND current edge < 2% | Dead capital, free it up |

### Edge Calculation

Uses the original `predicted_prob` stored at trade time (no re-prediction):

```
If side == YES:
  current_edge = predicted_prob - current_yes_price
If side == NO:
  current_edge = current_yes_price - predicted_prob
```

Round-trip fees (entry + exit) are subtracted:
```
current_edge_after_fees = current_edge - (2 * POLYMARKET_FEE)
```

At 2% fee per side, that's 4% total drag. The -5% threshold on `EXIT_NEGATIVE_EDGE_THRESHOLD` means the raw edge must be worse than -1% before fees trigger an exit.

### Max Possible Profit

```
If side == YES:
  shares = amount / entry_price
  max_profit = shares * 1.0 - amount  (shares pay $1 each if YES wins)
If side == NO:
  shares = amount / (1 - entry_price)
  max_profit = shares * 1.0 - amount  (shares pay $1 each if NO wins)
```

Note: unrealised PnL (from `calc_unrealised_pnl`) already subtracts entry fees. Max profit here is gross. This makes the 60% threshold effectively stricter (conservative, by design).

## Where It Runs

In `src/settler/settler.py`, added as a new step after the existing price refresh (`refresh_open_positions()`). The settler already fetches current prices for all open positions every cycle — this adds exit evaluation using that data.

### Settler Cycle (updated)

```
1. Fetch unresolved trades + open positions
2. Bulk fetch market data (prices + resolution status)
3. Update current_price on all open positions
4. Check for resolutions — settle any resolved markets FIRST
5. ** NEW: Evaluate exits for remaining open (non-resolved) positions **
6. Save PnL snapshot
7. Consolidate lessons (daily)
8. Send Telegram summaries
```

**Critical ordering:** Resolution checking (step 4) runs BEFORE exit evaluation (step 5). This prevents selling a position at $0.98 when it's about to resolve at $1.00. The exit evaluation query (`get_exit_candidates()`) only returns positions that are still open (not yet settled in this cycle).

Additionally, `_evaluate_exits()` skips any position where the fetched market data shows `closed=true` — as a safety net against the race condition where a market resolves between the bulk fetch and exit evaluation.

## Dry-Run vs Live Mode

- **Dry-run** (`EXIT_ENABLED=false` or positions with `dry_run` status): Position marked as `dry_run_exited` in DB with `exit_reason`. PnL calculated from `calc_unrealised_pnl()` at exit time. No SELL order placed. Logged and included in Telegram alerts.
- **Live** (`EXIT_ENABLED=true` and positions with `pending` status): SELL order placed via CLOB client. PnL recorded from actual SELL execution price (may differ from unrealised due to slippage). If SELL fails, log error, keep position open, retry next cycle.

## Sell Order Construction (Live Mode)

The executor's new `sell()` method:

```
1. Determine token to sell:
   - YES position → sell YES token (token_yes_id from market data)
   - NO position → sell NO token (token_no_id from market data)

2. Calculate shares to sell:
   - YES: shares = amount / entry_price
   - NO: shares = amount / (1 - entry_price)

3. Price: limit order at current market price (not market order)
   - Slight discount (0.5%) for guaranteed fill
   - YES sell price = current_yes_price * 0.995
   - NO sell price = (1 - current_yes_price) * 0.995

4. Place order via py_clob_client with side=SELL

5. Return execution result with actual fill price for PnL calculation
```

Note: `py_clob_client` supports SELL via `from py_clob_client.order_builder.constants import SELL`. The `price` stored in the trades table is always the YES price at entry time.

## Config

```env
EXIT_ENABLED=false
EXIT_STOP_LOSS_PCT=0.40
EXIT_NEGATIVE_EDGE_THRESHOLD=-0.05
EXIT_PROFIT_LOCK_PCT=0.60
EXIT_STALE_DAYS=30
EXIT_STALE_EDGE_THRESHOLD=0.02
```

All thresholds configurable. `EXIT_ENABLED=false` by default — opt-in. The negative edge threshold accounts for round-trip fees (2x POLYMARKET_FEE = 4%), so -5% means raw edge < -1%.

## DB Changes

### Migration: add `exit_reason` column to trades

```sql
ALTER TABLE trades ADD COLUMN exit_reason TEXT;
```

Null if position held to resolution or still open. Values: `stop_loss`, `negative_edge`, `profit_lock`, `stale_position`.

### New status values

- `dry_run_exited` — dry-run position closed by exit logic
- `exited` — live position closed by exit logic

### New DB methods

- `mark_trade_exited(trade_id, status, exit_reason, pnl)` — update trade status, exit_reason, pnl, and settled_at
- `get_exit_candidates()` — return open positions with `id`, `market_id`, `side`, `amount`, `price`, `current_price`, `predicted_prob`, `executed_at`, `status`. Filters: `status IN ('dry_run', 'pending')` AND `resolved_outcome IS NULL` AND `current_price IS NOT NULL` AND `predicted_prob IS NOT NULL`.

### Dashboard visibility

Update `get_all_settled_trades()` to include `dry_run_exited` and `exited` statuses so exited positions appear in the settled trades view alongside normally resolved trades.

## Files to Create/Modify

**Create:**
- `tests/test_exit_logic.py` — tests for exit rule evaluation

**Modify:**
- `src/settler/settler.py` — add `_evaluate_exits()` method, called after resolution settlement
- `src/risk/executor.py` — add `sell()` method for live SELL orders
- `src/db.py` — add migration for `exit_reason`, add `mark_trade_exited()`, `get_exit_candidates()`, update `get_all_settled_trades()`
- `src/config.py` — add exit threshold settings
- `src/notifications/telegram.py` — add `format_exit_alert()` for exit notifications

## Graceful Degradation

- Missing `current_price` or `predicted_prob` for a position: skip evaluation, don't exit on incomplete data
- Market shows `closed=true` in fetched data: skip exit evaluation (let settlement handle it)
- SELL order failure in live mode: log error, keep position open, retry next cycle
- Missing `executed_at` timestamp: skip stale position check
- Telegram notification failure: log warning, don't block exit execution

## Telegram Notifications

Each exit triggers a notification:
```
EXIT: [question]
Reason: [stop_loss|negative_edge|profit_lock|stale_position]
Side: YES | Entry: $0.35 | Current: $0.82
PnL: +$67.14 (locked in)
```

## Future Improvements

As model accuracy improves:
- Tighten thresholds (e.g., stop loss from 40% to 25%, edge threshold from -5% to -3%)
- Add re-prediction based exits (full model re-evaluation)
- Add trailing stop-loss (raise SL as position profits grow)
- Partial exits (sell half, hold half)
- Days-since-last-price-change metric for smarter stale detection
