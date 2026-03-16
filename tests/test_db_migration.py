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
