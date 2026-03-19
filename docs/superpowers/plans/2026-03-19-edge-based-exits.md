# Edge-Based Position Exits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exit rules to the settler that close positions when edge evaporates, losses mount, profits should be locked in, or capital goes stale.

**Architecture:** Four priority-ordered exit rules evaluated hourly in the settler after price refresh and AFTER settlement (to avoid selling positions about to resolve). Edge is computed from the original predicted_prob vs current market price. Dry-run positions are marked `dry_run_exited`; live positions get SELL orders via the CLOB client.

**Tech Stack:** Python 3.13, SQLite, httpx, py-clob-client, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-19-edge-based-exits-design.md`

---

## File Map

**Create:**
| File | Responsibility |
|---|---|
| `src/settler/exit_evaluator.py` | Pure logic: evaluate 4 exit rules against a position dict |
| `tests/test_exit_logic.py` | Tests for exit rule evaluation |

**Modify:**
| File | Change |
|---|---|
| `src/config.py:67-82` | Add 6 exit threshold settings |
| `src/db.py:235-247,530-569` | Add `exit_reason` migration, `mark_trade_exited()`, `get_exit_candidates()`, update `get_all_settled_trades()` |
| `src/risk/executor.py:14-74` | Add `sell()` method |
| `src/settler/settler.py:261-345` | Add `_evaluate_exits()` call after settlement |
| `src/notifications/telegram.py:53-76` | Add `format_exit_alert()` |
| `src/pnl.py` | No change needed — status change already excludes exited positions |

---

### Task 1: Add exit config settings

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: Add exit settings to Settings class**

In `src/config.py`, after the `ODDSPAPI_API_KEY` line (around line 74), add:

```python
    # Exit rules
    EXIT_ENABLED: bool = False
    EXIT_STOP_LOSS_PCT: float = 0.40
    EXIT_NEGATIVE_EDGE_THRESHOLD: float = -0.05
    EXIT_PROFIT_LOCK_PCT: float = 0.60
    EXIT_STALE_DAYS: int = 30
    EXIT_STALE_EDGE_THRESHOLD: float = 0.02
```

- [ ] **Step 2: Verify config loads**

Run: `python -c "from src.config import Settings; s = Settings(); print(s.EXIT_ENABLED, s.EXIT_STOP_LOSS_PCT)"`
Expected: `False 0.4`

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat: add exit rule threshold settings to config"
```

---

### Task 2: Add DB methods for exits

**Files:**
- Modify: `src/db.py`

- [ ] **Step 1: Add `exit_reason` column migration**

In `src/db.py`, in the `init()` method, after the existing `ALTER TABLE` migrations (search for the pattern — there are several `try/except` ALTER TABLE blocks), add:

```python
        # Add exit_reason column
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN exit_reason TEXT")
        except Exception:
            pass
```

- [ ] **Step 2: Add `mark_trade_exited()` method**

After the `settle_dry_run_trade()` method (around line 544), add:

```python
    def mark_trade_exited(self, trade_id: int, status: str, exit_reason: str, pnl: float):
        """Mark a trade as exited by the exit evaluator."""
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """UPDATE trades SET status = ?, exit_reason = ?, hypothetical_pnl = ?,
               settled_at = ? WHERE id = ?""",
            (status, exit_reason, pnl, now, trade_id),
        )
        conn.commit()

    def get_exit_candidates(self) -> list[dict]:
        """Get open positions eligible for exit evaluation."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT t.id, t.market_id, t.side, t.amount, t.price,
                      t.current_price, t.predicted_prob, t.executed_at, t.status,
                      ms.question
               FROM trades t
               LEFT JOIN (
                   SELECT condition_id, question,
                          ROW_NUMBER() OVER (PARTITION BY condition_id ORDER BY snapshot_at DESC) as rn
                   FROM market_snapshots
               ) ms ON t.market_id = ms.condition_id AND ms.rn = 1
               WHERE t.status IN ('dry_run', 'pending')
               AND t.resolved_outcome IS NULL
               AND t.current_price IS NOT NULL
               AND t.predicted_prob IS NOT NULL
               ORDER BY t.executed_at ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 3: Update `get_all_settled_trades()` to include exited statuses**

Change the WHERE clause in `get_all_settled_trades()` (line 238) from:

```python
        where = "WHERE status IN ('settled', 'dry_run_settled')"
```

to:

```python
        where = "WHERE status IN ('settled', 'dry_run_settled', 'exited', 'dry_run_exited')"
```

- [ ] **Step 4: Verify migration runs**

Run: `python -c "from src.db import Database; db = Database(':memory:'); db.init(); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/db.py
git commit -m "feat: add exit_reason column, mark_trade_exited, get_exit_candidates DB methods"
```

---

### Task 3: Create exit evaluator (pure logic)

**Files:**
- Create: `src/settler/exit_evaluator.py`
- Create: `tests/test_exit_logic.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_exit_logic.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta
from src.settler.exit_evaluator import evaluate_exit, ExitDecision
from src.pnl import calc_unrealised_pnl


def _make_position(side="YES", amount=50.0, entry_price=0.40, current_price=0.50,
                    predicted_prob=0.60, days_ago=5):
    executed_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "id": 1, "market_id": "test-market", "side": side, "amount": amount,
        "price": entry_price, "current_price": current_price,
        "predicted_prob": predicted_prob, "executed_at": executed_at,
        "status": "dry_run", "question": "Test market?",
    }


def test_no_exit_when_edge_healthy():
    """Position with positive edge should not trigger exit."""
    pos = _make_position(predicted_prob=0.60, current_price=0.50)
    result = evaluate_exit(pos, fee_rate=0.02)
    assert result is None


def test_stop_loss_triggers():
    """Position down > 40% of amount should trigger stop loss."""
    # YES at 0.40, now at 0.15 -> big loss
    pos = _make_position(entry_price=0.40, current_price=0.15)
    result = evaluate_exit(pos, fee_rate=0.02, stop_loss_pct=0.40)
    assert result is not None
    assert result.reason == "stop_loss"
    assert result.pnl < 0


def test_negative_edge_triggers():
    """Edge worse than -5% after round-trip fees should trigger exit."""
    # predicted_prob=0.50, current_price=0.60 -> raw edge = -0.10
    # after 2x fee (0.04): -0.14, way below -0.05 threshold
    pos = _make_position(predicted_prob=0.50, current_price=0.60)
    result = evaluate_exit(pos, fee_rate=0.02, negative_edge_threshold=-0.05)
    assert result is not None
    assert result.reason == "negative_edge"


def test_profit_lock_triggers():
    """Position with > 60% of max profit captured should lock in."""
    # YES at 0.20, now at 0.85 -> shares=250, unrealised ~212-50-1 = 161
    # max_profit = 250*1 - 50 = 200. 161/200 = 80.5% > 60%
    pos = _make_position(entry_price=0.20, current_price=0.85, predicted_prob=0.90)
    result = evaluate_exit(pos, fee_rate=0.02, profit_lock_pct=0.60)
    assert result is not None
    assert result.reason == "profit_lock"
    assert result.pnl > 0


def test_stale_position_triggers():
    """Position open > 30 days with low edge should exit."""
    pos = _make_position(predicted_prob=0.52, current_price=0.50, days_ago=35)
    result = evaluate_exit(pos, fee_rate=0.02, stale_days=30, stale_edge_threshold=0.02)
    assert result is not None
    assert result.reason == "stale_position"


def test_stale_position_does_not_trigger_if_edge_healthy():
    """Old position with good edge should NOT exit as stale."""
    pos = _make_position(predicted_prob=0.65, current_price=0.50, days_ago=35)
    result = evaluate_exit(pos, fee_rate=0.02, stale_days=30, stale_edge_threshold=0.02)
    assert result is None


def test_stop_loss_priority_over_negative_edge():
    """Stop loss should fire before negative edge (priority 1 > 2)."""
    # Big loss AND negative edge — stop loss should win
    pos = _make_position(entry_price=0.40, current_price=0.10, predicted_prob=0.30)
    result = evaluate_exit(pos, fee_rate=0.02, stop_loss_pct=0.40, negative_edge_threshold=-0.05)
    assert result is not None
    assert result.reason == "stop_loss"


def test_no_side_edge_calculation():
    """NO position edge: current_yes_price - predicted_prob."""
    # NO side: predicted_prob=0.70 (YES), we bet NO (30% implied)
    # current_yes=0.80 -> NO edge = 0.80 - 0.70 = +0.10 (good for us)
    pos = _make_position(side="NO", predicted_prob=0.70, current_price=0.80, entry_price=0.70)
    result = evaluate_exit(pos, fee_rate=0.02)
    assert result is None  # edge is positive, no exit

    # current_yes drops to 0.55 -> NO edge = 0.55 - 0.70 = -0.15 (bad for us)
    pos2 = _make_position(side="NO", predicted_prob=0.70, current_price=0.55, entry_price=0.70)
    result2 = evaluate_exit(pos2, fee_rate=0.02, negative_edge_threshold=-0.05)
    assert result2 is not None
    assert result2.reason == "negative_edge"


def test_skips_missing_data():
    """Missing current_price or predicted_prob should return None."""
    pos = _make_position()
    pos["current_price"] = None
    result = evaluate_exit(pos, fee_rate=0.02)
    assert result is None

    pos2 = _make_position()
    pos2["predicted_prob"] = None
    result2 = evaluate_exit(pos2, fee_rate=0.02)
    assert result2 is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_exit_logic.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement exit evaluator**

Create `src/settler/exit_evaluator.py`:

```python
from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from src.pnl import calc_unrealised_pnl

logger = logging.getLogger(__name__)


@dataclass
class ExitDecision:
    trade_id: int
    reason: str  # stop_loss, negative_edge, profit_lock, stale_position
    pnl: float
    current_edge: float
    question: str


def evaluate_exit(
    position: dict,
    fee_rate: float = 0.02,
    stop_loss_pct: float = 0.40,
    negative_edge_threshold: float = -0.05,
    profit_lock_pct: float = 0.60,
    stale_days: int = 30,
    stale_edge_threshold: float = 0.02,
) -> ExitDecision | None:
    """Evaluate whether a position should be exited.

    Returns ExitDecision if an exit rule triggers, None if position should be held.
    Rules are checked in priority order: stop_loss > negative_edge > profit_lock > stale.
    """
    current_price = position.get("current_price")
    predicted_prob = position.get("predicted_prob")
    if current_price is None or predicted_prob is None:
        return None

    side = position["side"]
    amount = position["amount"]
    entry_price = position["price"]
    trade_id = position["id"]
    question = position.get("question") or position.get("market_id", "unknown")

    # Calculate unrealised PnL
    pnl = calc_unrealised_pnl(side, amount, entry_price, current_price, fee_rate)

    # Calculate current edge (raw, then subtract round-trip fees)
    if side == "YES":
        raw_edge = predicted_prob - current_price
    else:
        raw_edge = current_price - predicted_prob
    edge_after_fees = raw_edge - (2 * fee_rate)

    # --- Rule 1: Stop loss (priority 1) ---
    if pnl < -(stop_loss_pct * amount):
        return ExitDecision(trade_id, "stop_loss", pnl, edge_after_fees, question)

    # --- Rule 2: Edge gone negative (priority 2) ---
    if edge_after_fees < negative_edge_threshold:
        return ExitDecision(trade_id, "negative_edge", pnl, edge_after_fees, question)

    # --- Rule 3: Profit lock-in (priority 3) ---
    if side == "YES":
        shares = amount / entry_price if entry_price > 0 else 0
    else:
        no_price = 1.0 - entry_price
        shares = amount / no_price if no_price > 0 else 0
    max_profit = shares * 1.0 - amount
    if max_profit > 0 and pnl > (profit_lock_pct * max_profit):
        return ExitDecision(trade_id, "profit_lock", pnl, edge_after_fees, question)

    # --- Rule 4: Stale position (priority 4) ---
    executed_at_str = position.get("executed_at")
    if executed_at_str:
        try:
            executed_at = datetime.fromisoformat(executed_at_str)
            if executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=timezone.utc)
            days_open = (datetime.now(timezone.utc) - executed_at).days
            if days_open > stale_days and edge_after_fees < stale_edge_threshold:
                return ExitDecision(trade_id, "stale_position", pnl, edge_after_fees, question)
        except (ValueError, TypeError):
            pass

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_exit_logic.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/settler/exit_evaluator.py tests/test_exit_logic.py
git commit -m "feat: add exit evaluator with stop-loss, negative-edge, profit-lock, and stale rules"
```

---

### Task 4: Add Telegram exit alert formatting

**Files:**
- Modify: `src/notifications/telegram.py`

- [ ] **Step 1: Add `format_exit_alert()` method**

After the `format_settlement_alert()` method (around line 73), add:

```python
    def format_exit_alert(self, question: str, reason: str, side: str,
                          entry_price: float, current_price: float,
                          pnl: float) -> str:
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        reason_display = reason.replace("_", " ").title()
        return (
            f"*Position Exit*\n"
            f"Market: {question}\n"
            f"Reason: {reason_display}\n"
            f"Side: {side} | Entry: ${entry_price:.2f} | Current: ${current_price:.2f}\n"
            f"PnL: {pnl_str}"
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/notifications/telegram.py
git commit -m "feat: add format_exit_alert to Telegram notifier"
```

---

### Task 5: Add `sell()` method to executor

**Files:**
- Modify: `src/risk/executor.py`

- [ ] **Step 1: Add `sell()` method**

After the `execute()` method (around line 74), add:

```python
    def sell(self, trade: dict, current_price: float) -> dict:
        """Place a SELL order to exit a position.

        Args:
            trade: dict with keys: id, market_id, side, amount, price (entry yes_price)
            current_price: current YES market price

        Returns:
            dict with keys: success (bool), order_id (str|None), fill_price (float|None)
        """
        try:
            from py_clob_client.order_builder.constants import SELL

            side = trade["side"]
            amount = trade["amount"]
            entry_price = trade["price"]

            # Determine token and share count
            if side == "YES":
                token_id = trade.get("token_yes_id", "")
                shares = amount / entry_price if entry_price > 0 else 0
                sell_price = round(current_price * 0.995, 2)  # 0.5% discount for fill
            else:
                token_id = trade.get("token_no_id", "")
                no_entry_price = 1.0 - entry_price
                shares = amount / no_entry_price if no_entry_price > 0 else 0
                sell_price = round((1.0 - current_price) * 0.995, 2)

            if not token_id or shares <= 0 or sell_price <= 0:
                logger.warning(f"Cannot sell trade {trade['id']}: invalid params")
                return {"success": False, "order_id": None, "fill_price": None}

            order_args = {
                "token_id": token_id,
                "price": sell_price,
                "size": round(shares, 2),
                "side": SELL,
            }
            response = self.clob.create_and_post_order(order_args)
            order_id = response.get("orderID", response.get("order_id", "unknown"))
            logger.info(f"SELL order placed: {order_id} | trade {trade['id']} | {shares:.2f} shares @ ${sell_price}")

            return {"success": True, "order_id": order_id, "fill_price": sell_price}

        except Exception as e:
            logger.error(f"SELL order failed for trade {trade['id']}: {e}")
            return {"success": False, "order_id": None, "fill_price": None}
```

- [ ] **Step 2: Commit**

```bash
git add src/risk/executor.py
git commit -m "feat: add sell() method to executor for position exits"
```

---

### Task 6: Wire exit evaluation into settler

**Files:**
- Modify: `src/settler/settler.py`

- [ ] **Step 1: Add import at top of settler.py**

After the existing imports (around line 10), add:

```python
from src.settler.exit_evaluator import evaluate_exit
```

- [ ] **Step 2: Add `_evaluate_exits()` method to Settler class**

After the `refresh_open_positions()` method (around line 260), add:

```python
    async def _evaluate_exits(self, market_data: dict[str, dict], settings=None) -> list[dict]:
        """Evaluate exit rules for all open positions. Returns list of exit actions taken."""
        if settings and not settings.EXIT_ENABLED and not any(
            t["status"] == "dry_run" for t in self.db.get_exit_candidates()
        ):
            return []

        candidates = self.db.get_exit_candidates()
        if not candidates:
            return []

        fee_rate = settings.POLYMARKET_FEE if settings else 0.02
        exits_taken = []

        for pos in candidates:
            # Skip markets that have resolved (avoid selling right before settlement)
            data = market_data.get(pos["market_id"])
            if data:
                closed = data.get("closed", False)
                if closed in (True, "true"):
                    continue

            decision = evaluate_exit(
                pos,
                fee_rate=fee_rate,
                stop_loss_pct=settings.EXIT_STOP_LOSS_PCT if settings else 0.40,
                negative_edge_threshold=settings.EXIT_NEGATIVE_EDGE_THRESHOLD if settings else -0.05,
                profit_lock_pct=settings.EXIT_PROFIT_LOCK_PCT if settings else 0.60,
                stale_days=settings.EXIT_STALE_DAYS if settings else 30,
                stale_edge_threshold=settings.EXIT_STALE_EDGE_THRESHOLD if settings else 0.02,
            )

            if decision is None:
                continue

            # Determine exit status based on trade status
            if pos["status"] == "dry_run":
                exit_status = "dry_run_exited"
            else:
                exit_status = "exited"

            # For live trades, attempt SELL (not implemented in dry-run)
            # Live sell would go here when executor is available

            self.db.mark_trade_exited(
                trade_id=decision.trade_id,
                status=exit_status,
                exit_reason=decision.reason,
                pnl=round(decision.pnl, 2),
            )

            logger.info(
                f"EXIT [{decision.reason}]: {decision.question[:60]} | "
                f"edge={decision.current_edge:.2%} | PnL=${decision.pnl:.2f}"
            )

            if self.notifier.is_enabled:
                msg = self.notifier.format_exit_alert(
                    question=decision.question,
                    reason=decision.reason,
                    side=pos["side"],
                    entry_price=pos["price"],
                    current_price=pos["current_price"],
                    pnl=decision.pnl,
                )
                try:
                    await self.notifier.send(msg)
                except Exception as e:
                    logger.warning(f"Exit notification failed: {e}")

            exits_taken.append({
                "trade_id": decision.trade_id,
                "reason": decision.reason,
                "pnl": decision.pnl,
            })

        if exits_taken:
            logger.info(f"Exited {len(exits_taken)} positions this cycle")

        return exits_taken
```

- [ ] **Step 3: Call `_evaluate_exits()` in `run()` after settlement**

In the `run()` method, find the settlement loop (the `for trade in trades:` block that ends around line 440). After the entire settlement for-loop but before the PnL snapshot and lesson consolidation, add:

```python
        # --- Exit evaluation (after settlement, so resolved markets are handled first) ---
        exits = await self._evaluate_exits(market_data, settings=self._settings)
```

This requires passing settings to the settler. Add a `settings` parameter:

In `__init__` (line 37), change:

```python
    def __init__(self, db: Database, notifier: TelegramNotifier,
                 gamma_url: str = "https://gamma-api.polymarket.com",
                 postmortem: "PostmortemAnalyzer | None" = None):
```

to:

```python
    def __init__(self, db: Database, notifier: TelegramNotifier,
                 gamma_url: str = "https://gamma-api.polymarket.com",
                 postmortem: "PostmortemAnalyzer | None" = None,
                 settings=None):
```

And add `self._settings = settings` after `self._last_positions_update = None` (line 45).

Also find where the Settler is instantiated (likely in `run.py` or a daemon script) and pass `settings` through. Search for `Settler(` in the codebase to find the callsite.

- [ ] **Step 4: Run pipeline and settler tests**

Run: `python -m pytest tests/test_exit_logic.py tests/test_pipeline.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: No new failures

- [ ] **Step 6: Commit**

```bash
git add src/settler/settler.py
git commit -m "feat: wire exit evaluation into settler cycle after settlement"
```

---

### Task 7: Integration test

**Files:**
- No new files — verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All previously-passing tests pass. New exit logic tests pass.

- [ ] **Step 2: Verify exit evaluator works end-to-end**

Run:
```python
python -c "
from src.settler.exit_evaluator import evaluate_exit
pos = {'id': 1, 'market_id': 'test', 'side': 'YES', 'amount': 50.0,
       'price': 0.40, 'current_price': 0.10, 'predicted_prob': 0.50,
       'executed_at': '2026-03-01T00:00:00+00:00', 'status': 'dry_run',
       'question': 'Test'}
result = evaluate_exit(pos, fee_rate=0.02)
print(f'Exit: {result.reason}, PnL: {result.pnl:.2f}')
"
```
Expected: `Exit: stop_loss, PnL: -38.50` (or similar negative)

- [ ] **Step 3: Verify DB migration**

Run:
```python
python -c "
from src.db import Database
db = Database(':memory:')
db.init()
# Save a dummy trade then exit it
db.save_trade('test-market', 'YES', 50.0, 0.40, None, 'dry_run', 0.60)
db.mark_trade_exited(1, 'dry_run_exited', 'stop_loss', -20.0)
candidates = db.get_exit_candidates()
print(f'Exit candidates (should be 0): {len(candidates)}')
settled = db.get_all_settled_trades()
print(f'Settled trades (should include exited): {len(settled)}')
print(f'Exit reason: {settled[0][\"exit_reason\"] if settled else \"N/A\"}')
"
```
Expected: 0 exit candidates (already exited), 1 settled trade with `exit_reason=stop_loss`

- [ ] **Step 4: Commit all**

```bash
git add -A
git commit -m "feat: edge-based position exit system"
```

---

## Post-Deployment Steps

1. Add to `.env` on the droplet:
```env
EXIT_ENABLED=false
EXIT_STOP_LOSS_PCT=0.40
EXIT_NEGATIVE_EDGE_THRESHOLD=-0.05
EXIT_PROFIT_LOCK_PCT=0.60
EXIT_STALE_DAYS=30
EXIT_STALE_EDGE_THRESHOLD=0.02
```

2. Deploy and restart settler:
```bash
cd /opt/polymarket-bot && git pull
sudo systemctl restart polymarket-settler
```

3. Monitor logs for exit evaluations:
```bash
journalctl -u polymarket-settler -f | grep EXIT
```

4. Check exit history:
```sql
sqlite3 data/polymarket.db "SELECT exit_reason, COUNT(*), ROUND(SUM(hypothetical_pnl),2) FROM trades WHERE exit_reason IS NOT NULL GROUP BY exit_reason;"
```
