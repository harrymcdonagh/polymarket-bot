import json
import os
import sqlite3
import pytest
from src.db import Database


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = Database(path=db_path)
    db.init()
    return db, db_path


def test_wal_mode_enabled(tmp_db):
    db, db_path = tmp_db
    conn = sqlite3.connect(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_busy_timeout_set(tmp_db):
    db, _ = tmp_db
    timeout = db._conn().execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout == 30000


def test_migrate_adds_settlement_columns(tmp_db):
    db, db_path = tmp_db
    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()]
    conn.close()
    assert "resolved_outcome" in cols
    assert "hypothetical_pnl" in cols
    assert "resolved_at" in cols
    assert "predicted_prob" in cols


def test_migrate_is_idempotent(tmp_db):
    db, _ = tmp_db
    # Running migrate again should not raise
    db.migrate()
    db.migrate()


def test_get_unresolved_dry_run_trades(tmp_db):
    db, _ = tmp_db
    db.save_trade("mkt1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    db.save_trade("mkt2", "NO", 5.0, 0.6, status="dry_run_settled", predicted_prob=0.3)
    unresolved = db.get_unresolved_dry_run_trades()
    assert len(unresolved) == 1
    assert unresolved[0]["market_id"] == "mkt1"
    assert unresolved[0]["predicted_prob"] == 0.7


def test_settle_dry_run_trade(tmp_db):
    db, _ = tmp_db
    db.save_trade("mkt1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)
    trades = db.get_unresolved_dry_run_trades()
    trade_id = trades[0]["id"]
    db.settle_dry_run_trade(trade_id, resolved_outcome="YES", hypothetical_pnl=5.0)
    conn = db._conn()
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert dict(row)["status"] == "dry_run_settled"
    assert dict(row)["resolved_outcome"] == "YES"
    assert dict(row)["hypothetical_pnl"] == 5.0
    assert dict(row)["resolved_at"] is not None


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


def test_get_all_settled_trades(tmp_db):
    db, _ = tmp_db
    db.save_trade("mkt1", "YES", 10.0, 0.5, status="pending")
    db.update_trade_status(1, "settled", pnl=5.0)
    db.save_trade("mkt2", "NO", 8.0, 0.6, status="dry_run", predicted_prob=0.3)
    db.settle_dry_run_trade(2, resolved_outcome="YES", hypothetical_pnl=-8.0)
    db.save_trade("mkt3", "YES", 5.0, 0.7, status="dry_run")  # not settled
    all_settled = db.get_all_settled_trades()
    assert len(all_settled) == 2


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
    from src.models import ScannedMarket
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


def test_features_json_column_exists(tmp_db):
    db, db_path = tmp_db
    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(predictions)").fetchall()]
    conn.close()
    assert "features_json" in cols


def test_save_prediction_with_features_json(tmp_db):
    db, _ = tmp_db
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
