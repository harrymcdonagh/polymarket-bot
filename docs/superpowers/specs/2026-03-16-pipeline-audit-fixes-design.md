# Pipeline Audit Fixes — Week-1 Data Collection

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement.

**Goal:** Fix the broken settlement → postmortem → learning loop so week-1 dry-run data collection produces usable training data and actionable insights.

**Context:** Bot is deployed on DigitalOcean droplet running 3 systemd services (bot loop, web dashboard, settler). Currently scanning markets, researching, predicting, and logging dry-run trades. But settled trades never feed back into postmortem or training.

---

## Architecture

Three services remain unchanged:
- `polymarket-bot` — main pipeline loop (scan → research → predict → risk → trade)
- `polymarket-web` — dashboard on port 8050
- `polymarket-settler` — checks Polymarket every 30 min for resolved markets

Fixes target the data flow AFTER settlement: settler → postmortem → metrics → trainer.

---

## Fix 1: Postmortem sees dry-run settled trades

### Problem
`db.get_losing_trades()` filters `WHERE status = 'settled'` but dry-run trades settle to `status = 'dry_run_settled'`. Postmortem gets zero input during week-1.

### Changes

**`src/db.py`** — Update `get_losing_trades()`:
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

**`src/db.py`** — Add `get_all_settled_trades()`:
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

---

## Fix 2: Rule-based metrics on every settled trade

### Problem
Only losing trades analyzed. No structured metrics tracked. Winning predictions ignored.

### Changes

**`src/db.py`** — New `trade_metrics` table:
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

**`src/settler/settler.py`** — After settling each trade, save rule-based metrics:
```python
# After self.db.settle_dry_run_trade(...)
was_correct = (trade["side"] == outcome)
self.db.save_trade_metric(
    trade_id=trade["id"],
    market_id=trade["market_id"],
    predicted_prob=trade.get("predicted_prob"),
    actual_outcome=outcome,
    predicted_side=trade["side"],
    was_correct=was_correct,
    edge_at_entry=None,  # looked up from predictions table
    confidence_at_entry=None,
    hypothetical_pnl=pnl,
    market_yes_price=trade["price"],
)
```

Enrich `edge_at_entry` and `confidence_at_entry` from the `predictions` table by joining on `market_id`.

---

## Fix 3: LLM postmortem only on high-confidence wrong predictions

### Problem
LLM postmortem is expensive. Running it on every trade wastes money. Running it on zero trades (current state) wastes the feature.

### Changes

**`src/settler/settler.py`** — Replace the blanket `if pnl < 0` check:
```python
# After settling and saving metrics
if not was_correct:
    # Look up prediction confidence/edge from predictions table
    pred = self.db.get_prediction_for_market(trade["market_id"])
    if pred and abs(pred.get("edge", 0)) > 0.05:
        # High-confidence wrong prediction — worth LLM analysis
        if self.postmortem:
            await self.postmortem.analyze_loss(
                question=question,
                predicted_prob=trade.get("predicted_prob", 0.5),
                actual_outcome=outcome,
                pnl=pnl,
                reasoning=f"Edge was {pred['edge']:.2%}, confidence {pred['confidence']:.2f}",
            )
```

**`src/db.py`** — Add helper:
```python
def get_prediction_for_market(self, market_id: str) -> dict | None:
    conn = self._conn()
    row = conn.execute(
        "SELECT * FROM predictions WHERE market_id = ? ORDER BY predicted_at DESC LIMIT 1",
        (market_id,),
    ).fetchone()
    return dict(row) if row else None
```

---

## Fix 4: Trainer uses real data (end-of-week retraining)

### Problem
`src/predictor/trainer.py` generates fake prices with `random.gauss()`. XGB trains on noise. No mechanism to train on week-1 outcomes.

### Changes

**`src/predictor/trainer.py`** — Rewrite `train_from_history()`:

```python
async def train_from_history(db_path: str = "data/polymarket.db") -> PredictionModel:
    """Train XGB model on real settled trade data."""
    db = Database(db_path)
    db.init()

    # Get all settled trades with their predictions
    conn = db._conn()
    rows = conn.execute("""
        SELECT p.market_yes_price, p.predicted_prob, p.xgb_prob, p.llm_prob,
               p.edge, p.confidence, p.recommended_side,
               t.resolved_outcome, t.side, t.price,
               tm.was_correct
        FROM predictions p
        JOIN trades t ON p.market_id = t.market_id
        LEFT JOIN trade_metrics tm ON t.id = tm.trade_id
        WHERE t.status IN ('settled', 'dry_run_settled')
        AND t.resolved_outcome IS NOT NULL
    """).fetchall()

    if len(rows) < 10:
        logger.warning(f"Only {len(rows)} settled trades — need at least 10 for training. Falling back to Gamma API.")
        return await _train_from_gamma_api()  # existing fallback

    # Build feature dicts and labels from real data
    feature_dicts = []
    labels = []
    for row in rows:
        features = {
            "yes_price": row["market_yes_price"],
            "no_price": 1.0 - row["market_yes_price"],
            "spread": 0.0,  # not stored in predictions, use 0
            "log_liquidity": 0.0,  # not available, use 0
            "log_volume_24h": 0.0,
            "days_to_resolution": 0,
            "volume_liquidity_ratio": 0.0,
            "flag_wide_spread": 0, "flag_high_volume": 0, "flag_price_spike": 0,
            "sentiment_positive_ratio": 0.0,
            "sentiment_negative_ratio": 0.0,
            "sentiment_neutral_ratio": 0.0,
            "sentiment_avg_score": 0.0,
            "sentiment_sample_size": 0,
            "sentiment_polarity": 0.0,
            "price_sentiment_gap": 0.0,
        }
        label = 1 if row["resolved_outcome"] == "YES" else 0
        feature_dicts.append(features)
        labels.append(label)

    model = PredictionModel()
    model.train(feature_dicts, labels)
    model.save("model_xgb.json")
    logger.info(f"Model trained on {len(labels)} real trades")
    return model
```

**Problem with above:** Many features (liquidity, volume, sentiment) aren't stored in the predictions table. This means the trained model only learns from price data, not the full feature set.

### Better approach: Store full feature dict in predictions

**`src/db.py`** — Add `features_json` column to predictions table:
```sql
ALTER TABLE predictions ADD COLUMN features_json TEXT;
```

**`src/pipeline.py`** — Pass features to `save_prediction()`:
```python
self.db.save_prediction(
    ...,
    features_json=json.dumps(features),  # the dict from extract_features()
)
```

Then the trainer can reconstruct the full feature dict from `features_json` instead of guessing missing values.

---

## Fix 5: Wire settler question/name into notifications

### Problem
Settler uses `trade["market_id"]` (a hex condition_id) in notifications and postmortem instead of the human-readable question.

### Changes

**`src/settler/settler.py`** — Look up question from market_snapshots:
```python
# At start of trade processing loop
question = trade.get("market_id")
snapshot = self.db.get_market_question(trade["market_id"])
if snapshot:
    question = snapshot
```

**`src/db.py`** — Add helper:
```python
def get_market_question(self, condition_id: str) -> str | None:
    conn = self._conn()
    row = conn.execute(
        "SELECT question FROM market_snapshots WHERE condition_id = ? ORDER BY snapshot_at DESC LIMIT 1",
        (condition_id,),
    ).fetchone()
    return row["question"] if row else None
```

---

## Summary of files changed

| File | Changes |
|------|---------|
| `src/db.py` | Fix `get_losing_trades()`, add `get_all_settled_trades()`, `save_trade_metric()`, `get_prediction_for_market()`, `get_market_question()`, new `trade_metrics` table, add `features_json` to predictions |
| `src/settler/settler.py` | Save rule-based metrics on every settlement, LLM postmortem only on high-confidence wrong predictions, use question names |
| `src/predictor/trainer.py` | Rewrite to use real settled data from DB, fall back to Gamma API if <10 trades |
| `src/pipeline.py` | Pass `features_json` to `save_prediction()` |

## What this does NOT change (intentionally)

- No auto-retraining during week 1 (manual `--train` at end of week)
- No auto-config updates from lessons (future enhancement)
- No changes to scanner, research, calibrator, or risk manager
- Settlement architecture stays as 3 separate services
- Dashboard stays as-is (already shows predictions + accuracy)

## Week-1 → Week-2 transition

At end of week 1:
1. SSH into droplet
2. `sudo systemctl stop polymarket-bot`
3. `/opt/polymarket-bot/venv/bin/python run.py --train` (uses real data)
4. Check dashboard for accuracy stats
5. If profitable: edit `.env` to remove `--live` guard, restart
6. If not: adjust thresholds, retrain, try another week of dry-run
