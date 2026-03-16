# Pipeline Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken settlement → postmortem → learning loop so week-1 dry-run data produces usable training data.

**Architecture:** Five targeted fixes to the data flow after settlement: (1) postmortem sees dry-run trades, (2) rule-based metrics on every settlement, (3) conditional LLM postmortem, (4) trainer uses real data, (5) human-readable market names in settler notifications.

**Tech Stack:** Python, SQLite, XGBoost, existing codebase patterns

**Spec:** `docs/superpowers/specs/2026-03-16-pipeline-audit-fixes-design.md`

---

## Chunk 1: Database Layer (Fixes 1, 2, 5)

### Task 1: Fix `get_losing_trades()` to include dry-run settled trades

**Files:**
- Modify: `src/db.py:146-152` (`get_losing_trades`)
- Test: `tests/test_db_migration.py`

- [ ] **Step 1: Write failing test**

In `tests/test_db_migration.py`, add:

```python
def test_get_losing_trades_includes_dry_run_settled(tmp_db):
    db, _ = tmp_db
    # Real settled loss
    db.save_trade("mkt1", "YES", 10.0, 0.5, status="pending")
    db.update_trade_status(1, "settled", pnl=-5.0)
    # Dry-run settled loss
    db.save_trade("mkt2", "NO", 8.0, 0.6, status="dry_run", predicted_prob=0.3)
    db.settle_dry_run_trade(2, resolved_outcome="YES", hypothetical_pnl=-8.0)
    losses = db.get_losing_trades()
    assert len(losses) == 2
    market_ids = {t["market_id"] for t in losses}
    assert "mkt1" in market_ids
    assert "mkt2" in market_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db_migration.py::test_get_losing_trades_includes_dry_run_settled -v`
Expected: FAIL — only 1 result (mkt1), dry_run_settled excluded

- [ ] **Step 3: Update `get_losing_trades()` in `src/db.py`**

Replace lines 146-152 with:

```python
def get_losing_trades(self, limit: int = 10) -> list[dict]:
    conn = self._conn()
    rows = conn.execute(
        """SELECT * FROM trades
           WHERE status IN ('settled', 'dry_run_settled')
           AND (pnl < 0 OR hypothetical_pnl < 0)
           ORDER BY COALESCE(settled_at, resolved_at) DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_db_migration.py::test_get_losing_trades_includes_dry_run_settled -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db.py tests/test_db_migration.py
git commit -m "fix: get_losing_trades includes dry_run_settled trades"
```

---

### Task 2: Add `get_all_settled_trades()` method

**Files:**
- Modify: `src/db.py` (add method after `get_losing_trades`)
- Test: `tests/test_db_migration.py`

- [ ] **Step 1: Write failing test**

```python
def test_get_all_settled_trades(tmp_db):
    db, _ = tmp_db
    db.save_trade("mkt1", "YES", 10.0, 0.5, status="pending")
    db.update_trade_status(1, "settled", pnl=5.0)
    db.save_trade("mkt2", "NO", 8.0, 0.6, status="dry_run", predicted_prob=0.3)
    db.settle_dry_run_trade(2, resolved_outcome="YES", hypothetical_pnl=-8.0)
    db.save_trade("mkt3", "YES", 5.0, 0.7, status="dry_run")  # not settled
    all_settled = db.get_all_settled_trades()
    assert len(all_settled) == 2
```

- [ ] **Step 2: Run test — should fail (method doesn't exist)**

- [ ] **Step 3: Add method to `src/db.py`**

After `get_losing_trades`, add:

```python
def get_all_settled_trades(self, limit: int = 50) -> list[dict]:
    """All settled trades (wins and losses, real and dry-run)."""
    conn = self._conn()
    rows = conn.execute(
        """SELECT * FROM trades
           WHERE status IN ('settled', 'dry_run_settled')
           ORDER BY COALESCE(settled_at, resolved_at) DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test — should pass**

- [ ] **Step 5: Commit**

```bash
git add src/db.py tests/test_db_migration.py
git commit -m "feat: add get_all_settled_trades method"
```

---

### Task 3: Add `trade_metrics` table and `save_trade_metric()` method

**Files:**
- Modify: `src/db.py` (add table to `init()`, add method)
- Test: `tests/test_db_migration.py`

- [ ] **Step 1: Write failing test**

```python
def test_save_and_query_trade_metric(tmp_db):
    db, _ = tmp_db
    db.save_trade("mkt1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    db.save_trade_metric(
        trade_id=1, market_id="mkt1", predicted_prob=0.7,
        actual_outcome="YES", predicted_side="YES", was_correct=True,
        edge_at_entry=0.10, confidence_at_entry=0.8,
        hypothetical_pnl=10.0, market_yes_price=0.5,
    )
    conn = db._conn()
    row = conn.execute("SELECT * FROM trade_metrics WHERE trade_id = 1").fetchone()
    assert row is not None
    assert row["was_correct"] == 1
    assert row["edge_at_entry"] == 0.10
```

- [ ] **Step 2: Run test — should fail**

- [ ] **Step 3: Add table to `init()` and add `save_trade_metric()`**

In `src/db.py`, inside `init()` `executescript`, add after the predictions table:

```sql
CREATE TABLE IF NOT EXISTS trade_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER REFERENCES trades(id),
    market_id TEXT NOT NULL,
    predicted_prob REAL,
    actual_outcome TEXT,
    predicted_side TEXT,
    was_correct INTEGER,
    edge_at_entry REAL,
    confidence_at_entry REAL,
    hypothetical_pnl REAL,
    market_yes_price REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

Add method:

```python
def save_trade_metric(self, trade_id: int, market_id: str, predicted_prob: float | None,
                      actual_outcome: str, predicted_side: str, was_correct: bool,
                      edge_at_entry: float | None, confidence_at_entry: float | None,
                      hypothetical_pnl: float, market_yes_price: float):
    conn = self._conn()
    conn.execute(
        """INSERT INTO trade_metrics
           (trade_id, market_id, predicted_prob, actual_outcome, predicted_side,
            was_correct, edge_at_entry, confidence_at_entry, hypothetical_pnl, market_yes_price)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade_id, market_id, predicted_prob, actual_outcome, predicted_side,
         1 if was_correct else 0, edge_at_entry, confidence_at_entry,
         hypothetical_pnl, market_yes_price),
    )
    conn.commit()
```

- [ ] **Step 4: Run test — should pass**

- [ ] **Step 5: Commit**

```bash
git add src/db.py tests/test_db_migration.py
git commit -m "feat: add trade_metrics table and save_trade_metric method"
```

---

### Task 4: Add `get_prediction_for_market()` and `get_market_question()` helpers

**Files:**
- Modify: `src/db.py`
- Test: `tests/test_db_migration.py`

- [ ] **Step 1: Write failing tests**

```python
def test_get_prediction_for_market(tmp_db):
    db, _ = tmp_db
    db.save_prediction(
        market_id="mkt1", question="Will X?", market_yes_price=0.5,
        predicted_prob=0.7, xgb_prob=0.6, llm_prob=0.75,
        edge=0.10, confidence=0.8, recommended_side="YES",
        approved=True, bet_size=5.0,
    )
    pred = db.get_prediction_for_market("mkt1")
    assert pred is not None
    assert pred["edge"] == 0.10
    assert db.get_prediction_for_market("nonexistent") is None


def test_get_market_question(tmp_db):
    db, _ = tmp_db
    from src.models import ScannedMarket, ScanFlag
    from datetime import datetime, timezone
    market = ScannedMarket(
        condition_id="0xabc", question="Will it rain?", slug="rain",
        token_yes_id="ty", token_no_id="tn",
        yes_price=0.5, no_price=0.5, spread=0.01,
        liquidity=10000, volume_24h=5000,
        end_date=None, days_to_resolution=10,
        flags=[], scanned_at=datetime.now(timezone.utc),
    )
    db.save_market_snapshots_batch([market])
    question = db.get_market_question("0xabc")
    assert question == "Will it rain?"
    assert db.get_market_question("nonexistent") is None
```

- [ ] **Step 2: Run tests — should fail**

- [ ] **Step 3: Add both methods to `src/db.py`**

```python
def get_prediction_for_market(self, market_id: str) -> dict | None:
    conn = self._conn()
    row = conn.execute(
        "SELECT * FROM predictions WHERE market_id = ? ORDER BY predicted_at DESC LIMIT 1",
        (market_id,),
    ).fetchone()
    return dict(row) if row else None

def get_market_question(self, condition_id: str) -> str | None:
    conn = self._conn()
    row = conn.execute(
        "SELECT question FROM market_snapshots WHERE condition_id = ? ORDER BY snapshot_at DESC LIMIT 1",
        (condition_id,),
    ).fetchone()
    return row["question"] if row else None
```

- [ ] **Step 4: Run tests — should pass**

- [ ] **Step 5: Commit**

```bash
git add src/db.py tests/test_db_migration.py
git commit -m "feat: add get_prediction_for_market and get_market_question helpers"
```

---

### Task 5: Add `features_json` column to predictions table

**Files:**
- Modify: `src/db.py` (migration + update `save_prediction`)
- Test: `tests/test_db_migration.py`

- [ ] **Step 1: Write failing test**

```python
def test_features_json_column_exists(tmp_db):
    db, db_path = tmp_db
    import sqlite3
    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(predictions)").fetchall()]
    conn.close()
    assert "features_json" in cols


def test_save_prediction_with_features_json(tmp_db):
    db, _ = tmp_db
    import json
    features = {"yes_price": 0.5, "spread": 0.02}
    db.save_prediction(
        market_id="mkt1", question="Test?", market_yes_price=0.5,
        predicted_prob=0.7, xgb_prob=0.6, llm_prob=0.75,
        edge=0.10, confidence=0.8, recommended_side="YES",
        approved=True, bet_size=5.0, features_json=json.dumps(features),
    )
    pred = db.get_prediction_for_market("mkt1")
    assert pred["features_json"] is not None
    assert json.loads(pred["features_json"])["yes_price"] == 0.5
```

- [ ] **Step 2: Run tests — should fail**

- [ ] **Step 3: Add column and update `save_prediction`**

In `src/db.py` `init()`, add `features_json TEXT` to the predictions CREATE TABLE.

Update `save_prediction()` signature to accept `features_json: str | None = None` and include it in the INSERT.

Add migration for existing DBs in `migrate()`:

```python
# Migrate predictions table
pred_cols = {row[1] for row in conn.execute("PRAGMA table_info(predictions)").fetchall()}
if "features_json" not in pred_cols:
    conn.execute("ALTER TABLE predictions ADD COLUMN features_json TEXT")
```

- [ ] **Step 4: Run tests — should pass**

- [ ] **Step 5: Run all DB tests**

Run: `python -m pytest tests/test_db_migration.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/db.py tests/test_db_migration.py
git commit -m "feat: add features_json column to predictions table"
```

---

## Chunk 2: Settler Fixes (Fixes 2, 3, 5)

### Task 6: Settler saves rule-based metrics on every settlement

**Files:**
- Modify: `src/settler/settler.py:81-102` (the settlement loop)
- Test: `tests/test_settler.py`

- [ ] **Step 1: Write failing test**

In `tests/test_settler.py`, add:

```python
@pytest.mark.asyncio
async def test_run_saves_trade_metrics(settler, tmp_db):
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    # Save a prediction so settler can look up edge/confidence
    tmp_db.save_prediction(
        market_id="cond-1", question="Test?", market_yes_price=0.5,
        predicted_prob=0.7, xgb_prob=0.6, llm_prob=0.75,
        edge=0.10, confidence=0.8, recommended_side="YES",
        approved=True, bet_size=5.0,
    )

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True, "resolved": True, "outcomePrices": "[\"1\",\"0\"]"
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        await settler.run()

    conn = tmp_db._conn()
    metric = conn.execute("SELECT * FROM trade_metrics WHERE trade_id = 1").fetchone()
    assert metric is not None
    assert metric["was_correct"] == 1
    assert metric["actual_outcome"] == "YES"
    assert metric["edge_at_entry"] == 0.10
```

- [ ] **Step 2: Run test — should fail**

- [ ] **Step 3: Update settler settlement loop**

In `src/settler/settler.py`, after `self.db.settle_dry_run_trade(...)`, add metrics saving:

```python
# Save rule-based metrics
was_correct = (trade["side"] == outcome)
pred = self.db.get_prediction_for_market(trade["market_id"])
self.db.save_trade_metric(
    trade_id=trade["id"],
    market_id=trade["market_id"],
    predicted_prob=trade.get("predicted_prob"),
    actual_outcome=outcome,
    predicted_side=trade["side"],
    was_correct=was_correct,
    edge_at_entry=pred.get("edge") if pred else None,
    confidence_at_entry=pred.get("confidence") if pred else None,
    hypothetical_pnl=pnl,
    market_yes_price=trade["price"],
)
```

- [ ] **Step 4: Run test — should pass**

- [ ] **Step 5: Commit**

```bash
git add src/settler/settler.py tests/test_settler.py
git commit -m "feat: settler saves rule-based metrics on every settlement"
```

---

### Task 7: Conditional LLM postmortem (high-confidence wrong predictions only)

**Files:**
- Modify: `src/settler/settler.py:104-115` (postmortem block)
- Test: `tests/test_settler.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_postmortem_skipped_for_low_edge_wrong(settler, tmp_db):
    """Postmortem should NOT run when edge < 5% even if wrong."""
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    tmp_db.save_prediction(
        market_id="cond-1", question="Test?", market_yes_price=0.5,
        predicted_prob=0.52, xgb_prob=0.5, llm_prob=0.53,
        edge=0.02, confidence=0.3, recommended_side="YES",
        approved=True, bet_size=5.0,
    )

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True, "resolved": True, "outcomePrices": "[\"0\",\"1\"]"
    }

    mock_postmortem = AsyncMock()
    mock_postmortem.analyze_loss = AsyncMock(return_value={})
    settler.postmortem = mock_postmortem

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        await settler.run()

    mock_postmortem.analyze_loss.assert_not_called()


@pytest.mark.asyncio
async def test_postmortem_runs_for_high_edge_wrong(settler, tmp_db):
    """Postmortem SHOULD run when edge > 5% and wrong."""
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    tmp_db.save_prediction(
        market_id="cond-1", question="Test?", market_yes_price=0.5,
        predicted_prob=0.7, xgb_prob=0.6, llm_prob=0.75,
        edge=0.15, confidence=0.8, recommended_side="YES",
        approved=True, bet_size=5.0,
    )

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True, "resolved": True, "outcomePrices": "[\"0\",\"1\"]"
    }

    mock_postmortem = AsyncMock()
    mock_postmortem.analyze_loss = AsyncMock(return_value={})
    settler.postmortem = mock_postmortem

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        await settler.run()

    mock_postmortem.analyze_loss.assert_called_once()
```

- [ ] **Step 2: Run tests — should fail**

- [ ] **Step 3: Replace postmortem block in settler**

Replace the existing postmortem block (lines 104-115) with:

```python
# LLM postmortem only on high-confidence wrong predictions
if not was_correct:
    pred = pred or self.db.get_prediction_for_market(trade["market_id"])
    if pred and abs(pred.get("edge", 0)) > 0.05 and self.postmortem:
        try:
            await self.postmortem.analyze_loss(
                question=question,
                predicted_prob=trade.get("predicted_prob", 0.5),
                actual_outcome=outcome,
                pnl=pnl,
                reasoning=f"Edge was {pred['edge']:.2%}, confidence {pred['confidence']:.2f}",
            )
        except Exception as e:
            logger.error(f"Postmortem failed for trade {trade['id']}: {e}")
```

- [ ] **Step 4: Run tests — should pass**

- [ ] **Step 5: Commit**

```bash
git add src/settler/settler.py tests/test_settler.py
git commit -m "feat: LLM postmortem only on high-confidence wrong predictions"
```

---

### Task 8: Use human-readable market names in settler notifications

**Files:**
- Modify: `src/settler/settler.py:81` (beginning of loop body)
- Test: `tests/test_settler.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_settler_uses_market_question_in_notification(settler, tmp_db):
    """Settler should use human-readable question, not condition_id hex."""
    from src.models import ScannedMarket
    from datetime import datetime, timezone
    market = ScannedMarket(
        condition_id="0xdeadbeef", question="Will BTC hit 100k?", slug="btc",
        token_yes_id="ty", token_no_id="tn",
        yes_price=0.5, no_price=0.5, spread=0.01,
        liquidity=10000, volume_24h=5000,
        end_date=None, days_to_resolution=10,
        flags=[], scanned_at=datetime.now(timezone.utc),
    )
    tmp_db.save_market_snapshots_batch([market])
    tmp_db.save_trade("0xdeadbeef", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True, "resolved": True, "outcomePrices": "[\"1\",\"0\"]"
    }

    notifier = MagicMock()
    notifier.is_enabled = True
    notifier.send = AsyncMock()
    notifier.format_settlement_alert = MagicMock(return_value="test msg")
    settler.notifier = notifier

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        await settler.run()

    call_args = notifier.format_settlement_alert.call_args
    assert call_args.kwargs.get("question", call_args[1].get("question", "")) == "Will BTC hit 100k?"
```

- [ ] **Step 2: Run test — should fail (currently passes condition_id)**

- [ ] **Step 3: Add question lookup at start of loop body**

At the top of the `for trade in trades:` loop, after `outcome = await self.check_resolution(...)` and before the pnl calculation, add:

```python
# Resolve human-readable question
question = trade["market_id"]
snapshot_question = self.db.get_market_question(trade["market_id"])
if snapshot_question:
    question = snapshot_question
```

Then update the notification call to use `question` instead of `trade["market_id"]`:

```python
msg = self.notifier.format_settlement_alert(
    question=question,
    ...
)
```

Also update the log line to use `question`.

- [ ] **Step 4: Run test — should pass**

- [ ] **Step 5: Run all settler tests**

Run: `python -m pytest tests/test_settler.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/settler/settler.py tests/test_settler.py
git commit -m "feat: settler uses human-readable market names"
```

---

## Chunk 3: Pipeline & Trainer (Fixes 4)

### Task 9: Pass `features_json` to `save_prediction()` in pipeline

**Files:**
- Modify: `src/pipeline.py:244-258` (save_prediction call)
- Test: `tests/test_predictor.py` (or integration-level)

- [ ] **Step 1: Write failing test**

In `tests/test_db_migration.py`:

```python
def test_pipeline_saves_features_json(tmp_db):
    """Verify save_prediction stores features_json when provided."""
    import json
    db, _ = tmp_db
    features = {"yes_price": 0.6, "spread": 0.02, "log_liquidity": 10.5}
    db.save_prediction(
        market_id="mkt1", question="Test?", market_yes_price=0.6,
        predicted_prob=0.7, xgb_prob=0.65, llm_prob=0.72,
        edge=0.10, confidence=0.8, recommended_side="YES",
        approved=True, bet_size=5.0,
        features_json=json.dumps(features),
    )
    pred = db.get_prediction_for_market("mkt1")
    stored = json.loads(pred["features_json"])
    assert stored["yes_price"] == 0.6
```

- [ ] **Step 2: Run test — should pass (already implemented in Task 5)**

- [ ] **Step 3: Update pipeline to pass features_json**

In `src/pipeline.py`, add `import json` at top. Then update the `save_prediction()` call to include:

```python
self.db.save_prediction(
    market_id=market.condition_id,
    question=market.question,
    market_yes_price=market.yes_price,
    predicted_prob=prediction.predicted_probability,
    xgb_prob=prediction.xgb_probability,
    llm_prob=prediction.llm_probability,
    edge=prediction.edge,
    confidence=prediction.confidence,
    recommended_side=prediction.recommended_side,
    approved=decision.approved,
    rejection_reason=decision.rejection_reason,
    bet_size=decision.bet_size_usd,
    features_json=json.dumps(features),
)
```

Note: `features` is already computed on line 160. Move the `save_prediction` call so `features` is in scope (it already is — `features` is defined on line 160, `save_prediction` is on line 245, both inside the same `for` loop body).

- [ ] **Step 4: Commit**

```bash
git add src/pipeline.py
git commit -m "feat: pipeline stores features_json with each prediction"
```

---

### Task 10: Rewrite trainer to use real settled data with Gamma API fallback

**Files:**
- Modify: `src/predictor/trainer.py`
- Test: `tests/test_predictor.py`

- [ ] **Step 1: Write failing test for real-data training path**

In `tests/test_predictor.py`, add:

```python
@pytest.mark.asyncio
async def test_train_from_history_uses_real_data(tmp_path):
    import json
    from src.db import Database

    db = Database(path=str(tmp_path / "test.db"))
    db.init()

    features_template = {
        "yes_price": 0.5, "no_price": 0.5, "spread": 0.02,
        "log_liquidity": 10.0, "log_volume_24h": 8.0,
        "days_to_resolution": 30, "volume_liquidity_ratio": 0.2,
        "flag_wide_spread": 0, "flag_high_volume": 0, "flag_price_spike": 0,
        "sentiment_positive_ratio": 0.5, "sentiment_negative_ratio": 0.3,
        "sentiment_neutral_ratio": 0.2, "sentiment_avg_score": 0.5,
        "sentiment_sample_size": 50, "sentiment_polarity": 0.2,
        "price_sentiment_gap": 0.0,
    }

    # Create 15 settled trades with predictions (need >=10)
    for i in range(15):
        mkt = f"mkt{i}"
        side = "YES" if i % 2 == 0 else "NO"
        outcome = "YES" if i % 3 != 0 else "NO"
        db.save_prediction(
            market_id=mkt, question=f"Q{i}?", market_yes_price=0.5,
            predicted_prob=0.6, xgb_prob=0.55, llm_prob=0.65,
            edge=0.10, confidence=0.7, recommended_side=side,
            approved=True, bet_size=5.0,
            features_json=json.dumps(features_template),
        )
        db.save_trade(mkt, side, 5.0, 0.5, status="dry_run", predicted_prob=0.6)
        db.settle_dry_run_trade(i + 1, resolved_outcome=outcome, hypothetical_pnl=3.0 if side == outcome else -5.0)

    from src.predictor.trainer import train_from_history
    model = await train_from_history(db_path=str(tmp_path / "test.db"))
    assert model.model is not None  # Should have trained successfully


@pytest.mark.asyncio
async def test_train_from_history_falls_back_with_few_trades(tmp_path):
    from src.predictor.trainer import train_from_history
    db = Database(path=str(tmp_path / "test.db"))
    db.init()
    # Only 2 trades — should fall back to Gamma API
    for i in range(2):
        db.save_trade(f"mkt{i}", "YES", 5.0, 0.5, status="dry_run", predicted_prob=0.6)
        db.settle_dry_run_trade(i + 1, resolved_outcome="YES", hypothetical_pnl=5.0)

    with patch("src.predictor.trainer.fetch_resolved_markets", return_value=[]):
        model = await train_from_history(db_path=str(tmp_path / "test.db"))
        # With no Gamma data and <10 real trades, returns untrained model
        assert model.model is None
```

- [ ] **Step 2: Run tests — should fail**

- [ ] **Step 3: Rewrite `train_from_history()` in `src/predictor/trainer.py`**

```python
async def train_from_history(db_path: str = "data/polymarket.db",
                             model_path: str = "model_xgb.json") -> PredictionModel:
    """Train XGB model on real settled trade data, fall back to Gamma API."""
    db = Database(db_path)
    db.init()

    conn = db._conn()
    rows = conn.execute("""
        SELECT p.features_json, p.market_yes_price, p.predicted_prob,
               t.resolved_outcome, t.side
        FROM predictions p
        JOIN trades t ON p.market_id = t.market_id
        WHERE t.status IN ('settled', 'dry_run_settled')
        AND t.resolved_outcome IS NOT NULL
        AND p.features_json IS NOT NULL
    """).fetchall()

    if len(rows) >= 10:
        logger.info(f"Training on {len(rows)} real settled trades")
        feature_dicts = []
        labels = []
        for row in rows:
            features = json.loads(row["features_json"])
            label = 1 if row["resolved_outcome"] == "YES" else 0
            feature_dicts.append(features)
            labels.append(label)

        model = PredictionModel()
        model.train(feature_dicts, labels)
        model.save(model_path)
        logger.info(f"Model trained on {len(labels)} real trades, saved to {model_path}")
        db.close()
        return model

    logger.warning(f"Only {len(rows)} real trades with features — falling back to Gamma API")
    db.close()
    return await _train_from_gamma_api(model_path)


async def _train_from_gamma_api(model_path: str = "model_xgb.json") -> PredictionModel:
    """Original training from Gamma API resolved markets."""
    markets = await fetch_resolved_markets(limit=2000)

    samples = []
    for m in markets:
        result = market_to_features(m)
        if result:
            samples.append(result)

    if len(samples) < 50:
        logger.warning(f"Only {len(samples)} usable Gamma API samples, need at least 50")
        return PredictionModel()

    samples.sort(key=lambda s: s["volume"], reverse=True)
    features = [s["features"] for s in samples]
    labels = [s["label"] for s in samples]

    yes_count = sum(labels)
    no_count = len(labels) - yes_count
    logger.info(f"Training on {len(samples)} Gamma markets (YES: {yes_count}, NO: {no_count})")

    model = PredictionModel()
    model.train(features, labels)
    model.save(model_path)
    logger.info(f"Model saved to {model_path}")
    return model
```

Update the `train_from_history` function signature to accept `db_path`. Add `from src.db import Database` import at top.

- [ ] **Step 4: Run tests — should pass**

- [ ] **Step 5: Run all predictor tests**

Run: `python -m pytest tests/test_predictor.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/predictor/trainer.py tests/test_predictor.py
git commit -m "feat: trainer uses real settled data with Gamma API fallback"
```

---

## Chunk 4: Run All Tests & Final Commit

### Task 11: Run full test suite and fix any issues

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 2: Fix any failures** (if needed)

- [ ] **Step 3: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: test suite cleanup for pipeline audit fixes"
```
