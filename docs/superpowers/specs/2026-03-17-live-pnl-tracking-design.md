# Live PnL Tracking Design

## Problem

PnL is only calculated at settlement — when a market resolves YES/NO. There is no visibility into how open positions are performing before resolution. The bot tracks the buy-in price but never checks the current market price again until the market closes.

## Solution

Extend the settler to refresh current market prices for all open positions each time it runs. Calculate unrealised PnL per position, store the latest price in the DB, surface it via Telegram and the dashboard API.

## Design

### Database Changes

Add two columns to the `trades` table via migration in `db.py`:

- `current_price REAL` — latest Gamma API YES price for this market
- `price_updated_at TEXT` — ISO timestamp of last price refresh

Unrealised PnL is calculated on the fly from `current_price` vs `price` (entry price), not stored separately. This avoids stale cached values.

New DB methods:
- `update_trade_price(trade_id, current_price)` — sets `current_price` and `price_updated_at`
- `get_open_positions_with_prices()` — returns unresolved trades with current price data, joined with market question from snapshots

### Settler Changes

New method `Settler.refresh_open_positions()`:

1. Fetch all unresolved dry-run trades (reuses existing query)
2. Deduplicate by `market_id` (one API call per market, not per trade)
3. For each unique market_id, call Gamma API `GET /markets?conditionId={id}` to get current `outcomePrices`
4. Update `trades.current_price` and `trades.price_updated_at` in the DB
5. Calculate unrealised PnL per position
6. Send Telegram position update if any open positions exist

New method `Settler.calc_unrealised_pnl(side, amount, entry_price, current_yes_price, fee_rate=0.02)`:

- YES side: `shares = amount / entry_price`, unrealised = `shares * current_yes_price - amount - fee`
- NO side: `shares = amount / (1 - entry_price)`, unrealised = `shares * (1 - current_yes_price) - amount - fee`

This mirrors the existing `calc_hypothetical_pnl` logic but uses the live market price instead of the binary $1/$0 resolved outcome.

Updated `Settler.run()` flow:
1. **Refresh prices** (new) — update current prices, send position update
2. Check resolutions (existing)
3. Settle resolved trades (existing)
4. Daily summary (existing, with new open positions line)

### Telegram Messages

**Per-run position update** — new `format_positions_update()` method on `TelegramNotifier`. Sent each settler run if there are open positions:

```
*Open Positions (3)*

Will Bitcoin hit $100k by June?
  YES @ $0.45 -> $0.52 | +$3.11 unrealised

Will the Fed cut rates in April?
  NO @ $0.70 -> $0.65 | +$1.42 unrealised

Will Tesla hit $300?
  YES @ $0.60 -> $0.55 | -$1.83 unrealised

*Total unrealised: +$2.70*
```

No message sent if zero open positions.

**Daily summary addition** — append open positions summary to existing daily summary message:

```
*Open positions:* 3 | Unrealised $2.70
```

### Dashboard API

New endpoint `GET /api/positions`:

```json
[
  {
    "trade_id": 5,
    "market_id": "0x...",
    "question": "Will Bitcoin hit $100k by June?",
    "side": "YES",
    "amount": 10.00,
    "entry_price": 0.45,
    "current_price": 0.52,
    "unrealised_pnl": 3.11,
    "price_updated_at": "2026-03-17T14:00:00Z"
  }
]
```

Add `unrealised_pnl` total to existing `GET /api/stats` response.

New `DashboardService.get_open_positions()` method that reads from DB and computes unrealised PnL per position.

## Files Changed

| File | Change |
|------|--------|
| `src/db.py` | Migration for new columns. `update_trade_price()`, `get_open_positions_with_prices()` |
| `src/settler/settler.py` | `refresh_open_positions()`, `calc_unrealised_pnl()`. Call refresh at start of `run()` |
| `src/notifications/telegram.py` | `format_positions_update()` |
| `src/dashboard/service.py` | `get_open_positions()` |
| `src/dashboard/web.py` | `GET /api/positions`, add unrealised PnL to stats |

No new files. No new dependencies. Uses existing Gamma API calls. Runs within existing settler loop cadence.
