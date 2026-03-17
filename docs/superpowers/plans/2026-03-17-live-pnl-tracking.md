# Live PnL Tracking Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track live unrealised PnL for open positions by refreshing current market prices each settler run, and surface it via Telegram and the dashboard API.

**Architecture:** Extend the settler loop with a price refresh step that queries Gamma API for current prices, stores them in the trades table, and calculates unrealised PnL on the fly. A standalone `calc_unrealised_pnl` function in `src/pnl.py` is shared by Settler and DashboardService.

**Tech Stack:** Python, SQLite, httpx, FastAPI, pytest

**Spec:** `docs/superpowers/specs/2026-03-17-live-pnl-tracking-design.md`

---

## File Structure

| File | Role |
|------|------|
| `src/pnl.py` | **Create.** Standalone `calc_unrealised_pnl()` function |
| `src/db.py` | **Modify.** Migration for `current_price`/`price_updated_at` columns, new query methods |
| `src/settler/settler.py` | **Modify.** `refresh_open_positions()`, `fetch_current_price()`, updated `run()` flow |
| `src/notifications/telegram.py` | **Modify.** `format_positions_update()` method |
| `src/dashboard/service.py` | **Modify.** `get_open_positions()` method |
| `src/dashboard/web.py` | **Modify.** `GET /api/positions` endpoint, unrealised PnL in stats |
| `tests/test_pnl.py` | **Create.** Tests for `calc_unrealised_pnl` |
| `tests/test_db_migration.py` | **Modify.** Tests for new columns and methods |
| `tests/test_settler.py` | **Modify.** Tests for `refresh_open_positions` |
| `tests/test_telegram.py` | **Modify.** Test for `format_positions_update` |
| `tests/test_web.py` | **Modify.** Test for `/api/positions` endpoint |

---

## Task 1: Standalone PnL calculation function

**Files:**
- Create: `src/pnl.py`
- Create: `tests/test_pnl.py`

- [ ] **Step 1: Write failing tests for `calc_unrealised_pnl`**

Create `tests/test_pnl.py`:

```python
import pytest
from src.pnl import calc_unrealised_pnl


def test_yes_side_price_up():
    # Bought YES at $0.40 for $10. Current price $0.60.
    # Shares = 10 / 0.40 = 25. Value = 25 * 0.60 = 15.
    # Fee = 10 * 0.02 = 0.20. PnL = 15 - 10 - 0.20 = 4.80
    pnl = calc_unrealised_pnl(side="YES", amount=10.0, entry_price=0.40, current_yes_price=0.60)
    assert pnl == pytest.approx(4.80)


def test_yes_side_price_down():
    # Bought YES at $0.60 for $10. Current price $0.40.
    # Shares = 10 / 0.60 = 16.667. Value = 16.667 * 0.40 = 6.667.
    # Fee = 0.20. PnL = 6.667 - 10 - 0.20 = -3.533
    pnl = calc_unrealised_pnl(side="YES", amount=10.0, entry_price=0.60, current_yes_price=0.40)
    assert pnl == pytest.approx(-3.5333, abs=0.01)


def test_no_side_price_down_is_profit():
    # Bought NO at yes_price $0.70 (NO price = $0.30) for $10.
    # Shares = 10 / 0.30 = 33.333. Current NO value = 1 - 0.80 = 0.20.
    # Value = 33.333 * 0.20 = 6.667. Fee = 0.20. PnL = 6.667 - 10 - 0.20 = -3.533
    # Wait -- NO profits when yes_price goes DOWN. Let's use yes going from 0.70 to 0.50.
    # NO price at entry = 0.30, shares = 10/0.30 = 33.333
    # Current NO price = 1 - 0.50 = 0.50. Value = 33.333 * 0.50 = 16.667
    # PnL = 16.667 - 10 - 0.20 = 6.467
    pnl = calc_unrealised_pnl(side="NO", amount=10.0, entry_price=0.70, current_yes_price=0.50)
    assert pnl == pytest.approx(6.4667, abs=0.01)


def test_no_side_price_up_is_loss():
    # Bought NO at yes_price $0.50 (NO price = $0.50) for $10.
    # Shares = 10 / 0.50 = 20. Current yes = 0.70, NO price = 0.30.
    # Value = 20 * 0.30 = 6.0. Fee = 0.20. PnL = 6.0 - 10 - 0.20 = -4.20
    pnl = calc_unrealised_pnl(side="NO", amount=10.0, entry_price=0.50, current_yes_price=0.70)
    assert pnl == pytest.approx(-4.20)


def test_guard_entry_price_zero():
    pnl = calc_unrealised_pnl(side="YES", amount=10.0, entry_price=0.0, current_yes_price=0.50)
    assert pnl == pytest.approx(-10.0)


def test_guard_entry_price_one():
    pnl = calc_unrealised_pnl(side="NO", amount=10.0, entry_price=1.0, current_yes_price=0.50)
    assert pnl == pytest.approx(-10.0)


def test_custom_fee_rate():
    # Same as test_yes_side_price_up but with 0% fee
    # PnL = 15 - 10 - 0 = 5.0
    pnl = calc_unrealised_pnl(side="YES", amount=10.0, entry_price=0.40, current_yes_price=0.60, fee_rate=0.0)
    assert pnl == pytest.approx(5.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pnl.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.pnl'`

- [ ] **Step 3: Write implementation**

Create `src/pnl.py`:

```python
def calc_unrealised_pnl(side: str, amount: float, entry_price: float,
                         current_yes_price: float, fee_rate: float = 0.02) -> float:
    """Calculate unrealised PnL for an open position at current market price.

    Uses the same logic as Settler.calc_hypothetical_pnl but with a live price
    instead of the binary $1/$0 resolved outcome.
    """
    if entry_price <= 0 or entry_price >= 1:
        return -amount

    fee = amount * fee_rate
    if side == "YES":
        shares = amount / entry_price
        return shares * current_yes_price - amount - fee
    else:  # NO
        no_share_price = 1.0 - entry_price
        shares = amount / no_share_price
        current_no_price = 1.0 - current_yes_price
        return shares * current_no_price - amount - fee
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pnl.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pnl.py tests/test_pnl.py
git commit -m "feat: add calc_unrealised_pnl standalone function with tests"
```

---

## Task 2: Database migration and new methods

**Files:**
- Modify: `src/db.py:130-147` (migrate method)
- Modify: `src/db.py` (add new methods)
- Modify: `tests/test_db_migration.py`

- [ ] **Step 1: Write failing tests for migration and new methods**

Add to `tests/test_db_migration.py`:

```python
def test_migrate_adds_current_price_columns(tmp_db):
    db, db_path = tmp_db
    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()]
    conn.close()
    assert "current_price" in cols
    assert "price_updated_at" in cols


def test_update_trade_price(tmp_db):
    db, _ = tmp_db
    db.save_trade("mkt1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    db.update_trade_price(1, 0.65)
    conn = db._conn()
    row = conn.execute("SELECT current_price, price_updated_at FROM trades WHERE id = 1").fetchone()
    assert row["current_price"] == 0.65
    assert row["price_updated_at"] is not None


def test_get_open_positions_with_prices(tmp_db):
    db, _ = tmp_db
    from src.models import ScannedMarket
    from datetime import datetime, timezone
    # Create a snapshot so the join resolves a question
    market = ScannedMarket(
        condition_id="mkt1", question="Will it rain?", slug="rain",
        token_yes_id="ty", token_no_id="tn",
        yes_price=0.5, no_price=0.5, spread=0.01,
        liquidity=10000, volume_24h=5000,
        end_date=None, days_to_resolution=10,
        flags=[], scanned_at=datetime.now(timezone.utc),
    )
    db.save_market_snapshots_batch([market])
    # Create open trades
    db.save_trade("mkt1", "YES", 10.0, 0.50, status="dry_run", predicted_prob=0.7)
    db.update_trade_price(1, 0.65)
    db.save_trade("mkt2", "NO", 5.0, 0.60, status="pending", predicted_prob=0.3)
    # Settled trade should not appear
    db.save_trade("mkt3", "YES", 8.0, 0.40, status="dry_run_settled", predicted_prob=0.6)
    positions = db.get_open_positions_with_prices()
    assert len(positions) == 2
    pos1 = next(p for p in positions if p["market_id"] == "mkt1")
    assert pos1["current_price"] == 0.65
    assert pos1["question"] == "Will it rain?"
    pos2 = next(p for p in positions if p["market_id"] == "mkt2")
    assert pos2["question"] is None  # no snapshot for mkt2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_migration.py::test_migrate_adds_current_price_columns tests/test_db_migration.py::test_update_trade_price tests/test_db_migration.py::test_get_open_positions_with_prices -v`
Expected: FAIL

- [ ] **Step 3: Add migration columns to `src/db.py`**

In the `migrate()` method (around line 134), add to the `migrations` list:

```python
        migrations = [
            ("resolved_outcome", "TEXT"),
            ("hypothetical_pnl", "REAL"),
            ("resolved_at", "TEXT"),
            ("predicted_prob", "REAL"),
            ("current_price", "REAL"),        # NEW
            ("price_updated_at", "TEXT"),      # NEW
        ]
```

- [ ] **Step 4: Add `update_trade_price` method to `Database`**

Add after `settle_dry_run_trade` (around line 440):

```python
    def update_trade_price(self, trade_id: int, current_price: float):
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE trades SET current_price = ?, price_updated_at = ? WHERE id = ?",
            (current_price, now, trade_id),
        )
        conn.commit()

    def get_open_positions_with_prices(self) -> list[dict]:
        """Get all unresolved trades (dry_run + pending) with current price and market question."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT t.*, ms.question
               FROM trades t
               LEFT JOIN (
                   SELECT condition_id, question,
                          ROW_NUMBER() OVER (PARTITION BY condition_id ORDER BY snapshot_at DESC) as rn
                   FROM market_snapshots
               ) ms ON t.market_id = ms.condition_id AND ms.rn = 1
               WHERE t.status IN ('dry_run', 'pending') AND t.resolved_outcome IS NULL
               ORDER BY t.executed_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_migration.py -v`
Expected: All tests PASS (including existing ones)

- [ ] **Step 6: Commit**

```bash
git add src/db.py tests/test_db_migration.py
git commit -m "feat: add current_price/price_updated_at migration and query methods"
```

---

## Task 3: Settler price refresh and Telegram position update

**Files:**
- Modify: `src/settler/settler.py:15-23` (init), `src/settler/settler.py:92-173` (run method)
- Modify: `src/notifications/telegram.py` (add format method)
- Modify: `tests/test_settler.py`
- Modify: `tests/test_telegram.py`

- [ ] **Step 1: Write test for `format_positions_update` on TelegramNotifier**

Add to `tests/test_telegram.py`:

```python
def test_format_positions_update(notifier):
    positions = [
        {"question": "Will X?", "side": "YES", "price": 0.45,
         "current_price": 0.52, "unrealised_pnl": 3.11},
        {"question": "Will Y?", "side": "NO", "price": 0.70,
         "current_price": 0.65, "unrealised_pnl": 1.42},
    ]
    msg = notifier.format_positions_update(positions, total_unrealised=4.53)
    assert "Open Positions (2)" in msg
    assert "Will X?" in msg
    assert "YES" in msg
    assert "$0.45" in msg
    assert "$0.52" in msg
    assert "+$3.11" in msg
    assert "+$4.53" in msg


def test_format_positions_update_negative_total(notifier):
    positions = [
        {"question": "Will X?", "side": "YES", "price": 0.60,
         "current_price": 0.40, "unrealised_pnl": -3.53},
    ]
    msg = notifier.format_positions_update(positions, total_unrealised=-3.53)
    assert "-$3.53" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_telegram.py::test_format_positions_update tests/test_telegram.py::test_format_positions_update_negative_total -v`
Expected: FAIL with `AttributeError: 'TelegramNotifier' object has no attribute 'format_positions_update'`

- [ ] **Step 3: Implement `format_positions_update` on `TelegramNotifier`**

Add to `src/notifications/telegram.py` after `format_startup` (line 88):

```python
    def format_positions_update(self, positions: list[dict], total_unrealised: float) -> str:
        total_str = f"+${total_unrealised:.2f}" if total_unrealised >= 0 else f"-${abs(total_unrealised):.2f}"
        lines = [f"*Open Positions ({len(positions)})*\n"]
        for p in positions:
            pnl = p["unrealised_pnl"]
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            lines.append(
                f"{p['question']}\n"
                f"  {p['side']} @ ${p['price']:.2f} -> ${p['current_price']:.2f} | {pnl_str} unrealised"
            )
        lines.append(f"\n*Total unrealised: {total_str}*")
        return "\n".join(lines)
```

- [ ] **Step 4: Run telegram tests to verify they pass**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit telegram changes**

```bash
git add src/notifications/telegram.py tests/test_telegram.py
git commit -m "feat: add format_positions_update to TelegramNotifier"
```

- [ ] **Step 6: Write tests for `refresh_open_positions` on Settler**

Add to `tests/test_settler.py`:

```python
@pytest.mark.asyncio
async def test_refresh_open_positions_updates_prices(settler, tmp_db):
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"resolved": False, "outcomePrices": "[\"0.65\",\"0.35\"]"}
    ]

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        await settler.refresh_open_positions()

    conn = tmp_db._conn()
    row = conn.execute("SELECT current_price, price_updated_at FROM trades WHERE id = 1").fetchone()
    assert row["current_price"] == pytest.approx(0.65)
    assert row["price_updated_at"] is not None


@pytest.mark.asyncio
async def test_refresh_open_positions_handles_api_failure(settler, tmp_db):
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)

    mock_response = AsyncMock()
    mock_response.status_code = 500
    mock_response.json.return_value = {}

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        # Should not raise
        await settler.refresh_open_positions()

    conn = tmp_db._conn()
    row = conn.execute("SELECT current_price FROM trades WHERE id = 1").fetchone()
    assert row["current_price"] is None  # not updated


@pytest.mark.asyncio
async def test_refresh_deduplicates_api_calls(settler, tmp_db):
    # Two trades on same market should result in one API call
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    tmp_db.save_trade("cond-1", "NO", 5.0, 0.5, status="dry_run", predicted_prob=0.3)

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"resolved": False, "outcomePrices": "[\"0.60\",\"0.40\"]"}
    ]

    with patch("httpx.AsyncClient.get", return_value=mock_response) as mock_get:
        await settler.refresh_open_positions()

    # Should only call API once for the deduplicated market_id
    assert mock_get.call_count == 1

    conn = tmp_db._conn()
    rows = conn.execute("SELECT current_price FROM trades WHERE market_id = 'cond-1'").fetchall()
    assert all(r["current_price"] == pytest.approx(0.60) for r in rows)


@pytest.mark.asyncio
async def test_run_calls_refresh_before_settlement(settler, tmp_db):
    """Verify run() calls refresh_open_positions before checking resolutions."""
    call_order = []

    async def mock_refresh():
        call_order.append("refresh")

    original_run = settler.run

    with patch.object(settler, "refresh_open_positions", side_effect=mock_refresh):
        # Add a trade so the resolution path runs
        tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"resolved": False}
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            await settler.run()

    assert call_order[0] == "refresh"
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `python -m pytest tests/test_settler.py::test_refresh_open_positions_updates_prices tests/test_settler.py::test_refresh_open_positions_handles_api_failure tests/test_settler.py::test_refresh_deduplicates_api_calls tests/test_settler.py::test_run_calls_refresh_before_settlement -v`
Expected: FAIL

- [ ] **Step 8: Implement `fetch_current_price` and `refresh_open_positions` on Settler**

In `src/settler/settler.py`, add import at top:

```python
from src.pnl import calc_unrealised_pnl
```

Add `_last_positions_update` to `__init__` (line 23):

```python
        self._last_positions_update: str | None = None
```

Add new methods after `calc_hypothetical_pnl` (after line 90):

```python
    async def fetch_current_price(self, condition_id: str) -> float | None:
        """Fetch current YES price from Gamma API for an active market."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.gamma_url}/markets",
                    params={"conditionId": condition_id},
                )
                if resp.status_code != 200:
                    logger.warning(f"Gamma API returned {resp.status_code} for price check {condition_id}")
                    return None
                raw = resp.json()
                results = (await raw) if hasattr(raw, "__await__") else raw
                if isinstance(results, list):
                    if not results:
                        return None
                    data = results[0]
                else:
                    data = results

            prices_str = data.get("outcomePrices", "[]")
            prices = json.loads(prices_str)
            if len(prices) >= 2:
                return float(prices[0])
            return None
        except Exception as e:
            logger.warning(f"Price fetch failed for {condition_id}: {e}")
            return None

    async def refresh_open_positions(self) -> None:
        """Refresh current prices for all open positions and optionally send Telegram update."""
        trades = self.db.get_open_positions_with_prices()
        if not trades:
            return

        # Deduplicate API calls by market_id
        market_ids = {t["market_id"] for t in trades}
        prices: dict[str, float] = {}
        for market_id in market_ids:
            price = await self.fetch_current_price(market_id)
            if price is not None:
                prices[market_id] = price

        # Update DB and build position summaries
        positions = []
        for trade in trades:
            current_price = prices.get(trade["market_id"])
            if current_price is None:
                continue
            self.db.update_trade_price(trade["id"], current_price)
            pnl = calc_unrealised_pnl(
                side=trade["side"],
                amount=trade["amount"],
                entry_price=trade["price"],
                current_yes_price=current_price,
            )
            question = trade.get("question") or trade["market_id"]
            positions.append({
                "question": question,
                "side": trade["side"],
                "price": trade["price"],
                "current_price": current_price,
                "unrealised_pnl": pnl,
            })

        if not positions:
            return

        total_unrealised = sum(p["unrealised_pnl"] for p in positions)
        logger.info(f"Refreshed {len(positions)} positions, total unrealised: ${total_unrealised:.2f}")

        # Throttle Telegram updates to once per 6 hours
        now = datetime.now(timezone.utc)
        should_send = True
        if self._last_positions_update:
            last = datetime.fromisoformat(self._last_positions_update)
            if (now - last).total_seconds() < 6 * 3600:
                should_send = False

        if should_send and self.notifier.is_enabled:
            msg = self.notifier.format_positions_update(positions, total_unrealised)
            await self.notifier.send(msg)
            self._last_positions_update = now.isoformat()
```

- [ ] **Step 9: Update `run()` to call `refresh_open_positions` first**

At the start of `run()` (line 93), add before existing logic:

```python
    async def run(self) -> None:
        """Check all unresolved dry-run trades and settle any that have resolved."""
        await self.refresh_open_positions()

        trades = self.db.get_unresolved_dry_run_trades()
        # ... rest of existing code unchanged
```

- [ ] **Step 10: Update daily summary to include open positions**

In `_maybe_send_daily_summary` (around line 200), after the existing PnL line, add open positions info. Use sign-aware formatting to avoid `$-2.70`:

```python
        # After the existing msg = (...) block, before await self.notifier.send(msg):
        open_positions = self.db.get_open_positions_with_prices()
        if open_positions:
            total_unrealised = sum(
                calc_unrealised_pnl(
                    side=t["side"], amount=t["amount"],
                    entry_price=t["price"], current_yes_price=t["current_price"],
                )
                for t in open_positions if t.get("current_price") is not None
            )
            ur_str = f"+${total_unrealised:.2f}" if total_unrealised >= 0 else f"-${abs(total_unrealised):.2f}"
            msg += f"\n*Open positions:* {len(open_positions)} | Unrealised {ur_str}"
```

- [ ] **Step 11: Update existing settler tests to mock `refresh_open_positions`**

The existing tests in `test_settler.py` (`test_run_settles_resolved_trades`, `test_run_saves_trade_metrics`, `test_postmortem_skipped_for_low_edge_wrong`, `test_postmortem_runs_for_high_edge_wrong`) all call `settler.run()` and mock `httpx.AsyncClient.get` with a resolution response. Since `run()` now calls `refresh_open_positions()` first (which also calls the Gamma API), these tests will break.

Fix: patch `refresh_open_positions` as a no-op in all existing `run()` tests. Add this helper and update each test:

```python
# Add this import at the top if not already present
from unittest.mock import patch

# In each existing test that calls settler.run(), wrap with:
with patch.object(settler, "refresh_open_positions", new_callable=AsyncMock):
    # ... existing test body with httpx mock and await settler.run()
```

Specifically update these 4 tests:
- `test_run_settles_resolved_trades` (line 76)
- `test_run_saves_trade_metrics` (line 96)
- `test_postmortem_skipped_for_low_edge_wrong` (line 123)
- `test_postmortem_runs_for_high_edge_wrong` (line 150)

Each one needs `refresh_open_positions` patched out so the httpx mock only serves the resolution check.

- [ ] **Step 12: Run all settler tests**

Run: `python -m pytest tests/test_settler.py -v`
Expected: All tests PASS (new + updated existing)

- [ ] **Step 12: Commit**

```bash
git add src/settler/settler.py tests/test_settler.py
git commit -m "feat: add live price refresh and position updates to settler"
```

---

## Task 4: Dashboard API endpoint

**Files:**
- Modify: `src/dashboard/service.py:61-72` (get_stats), add `get_open_positions`
- Modify: `src/dashboard/web.py` (add endpoint)
- Modify: `tests/test_web.py`

- [ ] **Step 1: Write failing test for `/api/positions` endpoint**

Add to `tests/test_web.py`:

```python
def test_get_positions(client):
    resp = client.get("/api/positions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_stats_include_unrealised_pnl(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "unrealised_pnl" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web.py::test_get_positions tests/test_web.py::test_stats_include_unrealised_pnl -v`
Expected: FAIL

- [ ] **Step 3: Add `get_open_positions` to DashboardService**

Add to `src/dashboard/service.py` after `get_pnl_history` (around line 87):

```python
    def get_open_positions(self) -> list[dict]:
        from src.pnl import calc_unrealised_pnl
        positions = self.db.get_open_positions_with_prices()
        result = []
        for p in positions:
            current_price = p.get("current_price")
            pnl = None
            if current_price is not None:
                pnl = calc_unrealised_pnl(
                    side=p["side"],
                    amount=p["amount"],
                    entry_price=p["price"],
                    current_yes_price=current_price,
                )
            result.append({
                "trade_id": p["id"],
                "market_id": p["market_id"],
                "question": p.get("question") or p["market_id"],
                "side": p["side"],
                "amount": p["amount"],
                "entry_price": p["price"],
                "current_price": current_price,
                "unrealised_pnl": round(pnl, 2) if pnl is not None else None,
                "price_updated_at": p.get("price_updated_at"),
            })
        return result
```

- [ ] **Step 4: Add `unrealised_pnl` to `get_stats`**

In `src/dashboard/service.py` `get_stats()` method (around line 61), add after the return dict is built:

```python
    def get_stats(self) -> dict:
        trade_stats = self.db.get_trade_stats()
        pred_stats = self.db.get_prediction_stats()
        accuracy = self.db.get_prediction_accuracy()
        # Calculate total unrealised PnL from open positions
        from src.pnl import calc_unrealised_pnl
        open_pos = self.db.get_open_positions_with_prices()
        unrealised = sum(
            calc_unrealised_pnl(
                side=t["side"], amount=t["amount"],
                entry_price=t["price"], current_yes_price=t["current_price"],
            )
            for t in open_pos if t.get("current_price") is not None
        )
        return {
            **trade_stats,
            **pred_stats,
            "prediction_accuracy": accuracy,
            "open_trades": len(self.db.get_open_trades()),
            "today_pnl": self.db.get_daily_pnl(),
            "snapshot_count": self.db.get_snapshot_count(),
            "unrealised_pnl": round(unrealised, 2),
        }
```

- [ ] **Step 5: Add `/api/positions` endpoint to web.py**

In `src/dashboard/web.py`, add after `api_pnl_history` (around line 118):

```python
    @app.get("/api/positions")
    async def api_positions():
        return await asyncio.to_thread(service.get_open_positions)
```

- [ ] **Step 6: Run web tests**

Run: `python -m pytest tests/test_web.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/dashboard/service.py src/dashboard/web.py tests/test_web.py
git commit -m "feat: add /api/positions endpoint and unrealised PnL to stats"
```

---

## Task 5: Integration test and final verification

**Files:**
- All modified files

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS, no regressions

- [ ] **Step 2: Verify migration is idempotent**

Run: `python -m pytest tests/test_db_migration.py::test_migrate_is_idempotent -v`
Expected: PASS

- [ ] **Step 3: Commit any final fixes if needed**

Only if tests revealed issues.
