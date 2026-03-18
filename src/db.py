import sqlite3
import threading
from datetime import datetime, timezone


class Database:
    def __init__(self, path: str = "bot.db"):
        self.path = path
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.path)
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA busy_timeout=30000")
        return self._local.connection

    def close(self):
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None

    def init(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scanned_markets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                condition_id TEXT NOT NULL,
                question TEXT,
                yes_price REAL,
                no_price REAL,
                spread REAL,
                liquidity REAL,
                volume_24h REAL,
                flags TEXT,
                scanned_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                condition_id TEXT NOT NULL,
                question TEXT,
                yes_price REAL,
                no_price REAL,
                spread REAL,
                liquidity REAL,
                volume_24h REAL,
                days_to_resolution INTEGER,
                flags TEXT,
                snapshot_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                side TEXT NOT NULL,
                amount REAL NOT NULL,
                price REAL NOT NULL,
                order_id TEXT,
                status TEXT DEFAULT 'pending',
                pnl REAL,
                executed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                settled_at TEXT
            );
            CREATE TABLE IF NOT EXISTS postmortems (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER REFERENCES trades(id),
                market_id TEXT NOT NULL,
                question TEXT,
                predicted_prob REAL,
                actual_outcome TEXT,
                pnl REAL,
                failure_reasons TEXT,
                lessons TEXT,
                system_updates TEXT,
                analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                lesson TEXT NOT NULL,
                source_trade_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS consolidated_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ruleset TEXT NOT NULL,
                feature_suggestions TEXT,
                lesson_count INTEGER,
                consolidated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                question TEXT,
                market_yes_price REAL,
                predicted_prob REAL,
                xgb_prob REAL,
                llm_prob REAL,
                edge REAL,
                confidence REAL,
                recommended_side TEXT,
                approved INTEGER DEFAULT 0,
                rejection_reason TEXT,
                bet_size REAL,
                features_json TEXT,
                predicted_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
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
            CREATE TABLE IF NOT EXISTS pnl_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                settled_pnl REAL NOT NULL,
                unrealised_pnl REAL NOT NULL,
                total_pnl REAL NOT NULL,
                open_positions INTEGER NOT NULL,
                snapshot_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_at ON pnl_snapshots(snapshot_at);
            CREATE INDEX IF NOT EXISTS idx_lessons_category ON lessons(category);
            CREATE INDEX IF NOT EXISTS idx_trades_market_id ON trades(market_id);
            CREATE INDEX IF NOT EXISTS idx_predictions_market_id ON predictions(market_id);
            CREATE INDEX IF NOT EXISTS idx_trade_metrics_trade_id ON trade_metrics(trade_id);
            CREATE INDEX IF NOT EXISTS idx_market_snapshots_condition_id ON market_snapshots(condition_id);
            CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON trades(executed_at);
            CREATE INDEX IF NOT EXISTS idx_trades_settled_at ON trades(settled_at);
            CREATE INDEX IF NOT EXISTS idx_market_snapshots_snapshot_at ON market_snapshots(snapshot_at);
            CREATE INDEX IF NOT EXISTS idx_predictions_predicted_at ON predictions(predicted_at);
            CREATE INDEX IF NOT EXISTS idx_market_snapshots_cond_time ON market_snapshots(condition_id, snapshot_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_lessons_unique ON lessons(category, lesson);
        """)
        conn.commit()
        self.migrate()

    def migrate(self):
        """Add columns that don't exist yet. Safe to run repeatedly."""
        conn = self._conn()
        existing = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        migrations = [
            ("resolved_outcome", "TEXT"),
            ("hypothetical_pnl", "REAL"),
            ("resolved_at", "TEXT"),
            ("predicted_prob", "REAL"),
            ("current_price", "REAL"),
            ("price_updated_at", "TEXT"),
            ("postmortem_done", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_type in migrations:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
        # Migrate predictions table
        pred_cols = {row[1] for row in conn.execute("PRAGMA table_info(predictions)").fetchall()}
        if "features_json" not in pred_cols:
            conn.execute("ALTER TABLE predictions ADD COLUMN features_json TEXT")
        # Migrate market_snapshots table
        snap_cols = {row[1] for row in conn.execute("PRAGMA table_info(market_snapshots)").fetchall()}
        if "token_yes_id" not in snap_cols:
            conn.execute("ALTER TABLE market_snapshots ADD COLUMN token_yes_id TEXT")
        if "slug" not in snap_cols:
            conn.execute("ALTER TABLE market_snapshots ADD COLUMN slug TEXT")
        # Migrate pnl_snapshots table
        pnl_cols = {row[1] for row in conn.execute("PRAGMA table_info(pnl_snapshots)").fetchall()}
        if "win_rate" not in pnl_cols:
            conn.execute("ALTER TABLE pnl_snapshots ADD COLUMN win_rate REAL")
        if "brier_score" not in pnl_cols:
            conn.execute("ALTER TABLE pnl_snapshots ADD COLUMN brier_score REAL")
        conn.commit()

    def save_trade(self, market_id: str, side: str, amount: float, price: float,
                   order_id: str | None = None, status: str = "pending",
                   predicted_prob: float | None = None):
        conn = self._conn()
        conn.execute(
            "INSERT INTO trades (market_id, side, amount, price, order_id, status, predicted_prob) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (market_id, side, amount, price, order_id, status, predicted_prob),
        )
        conn.commit()

    def get_open_trades(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute("SELECT * FROM trades WHERE status = 'pending'").fetchall()
        return [dict(r) for r in rows]

    def update_trade_status(self, trade_id: int, status: str, pnl: float | None = None,
                            expected_status: str | None = None):
        """Update trade status. If expected_status given, only update if current status matches (atomic)."""
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        if pnl is not None:
            if expected_status:
                cursor = conn.execute(
                    "UPDATE trades SET status = ?, pnl = ?, settled_at = ? WHERE id = ? AND status = ?",
                    (status, pnl, now, trade_id, expected_status),
                )
            else:
                cursor = conn.execute(
                    "UPDATE trades SET status = ?, pnl = ?, settled_at = ? WHERE id = ?",
                    (status, pnl, now, trade_id),
                )
        else:
            if expected_status:
                cursor = conn.execute(
                    "UPDATE trades SET status = ? WHERE id = ? AND status = ?",
                    (status, trade_id, expected_status),
                )
            else:
                cursor = conn.execute(
                    "UPDATE trades SET status = ? WHERE id = ?", (status, trade_id),
                )
        conn.commit()
        return cursor.rowcount > 0

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

    def get_all_settled_trades(self, limit: int = 50, exclude_postmortem_done: bool = False) -> list[dict]:
        """All settled trades (wins and losses, real and dry-run)."""
        conn = self._conn()
        where = "WHERE status IN ('settled', 'dry_run_settled')"
        if exclude_postmortem_done:
            where += " AND COALESCE(postmortem_done, 0) = 0"
        rows = conn.execute(
            f"""SELECT * FROM trades
               {where}
               ORDER BY COALESCE(settled_at, resolved_at) DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_postmortem_done(self, trade_id: int):
        """Mark a trade as having had its postmortem analysis completed."""
        conn = self._conn()
        conn.execute("UPDATE trades SET postmortem_done = 1 WHERE id = ?", (trade_id,))
        conn.commit()

    def save_lesson(self, category: str, lesson: str, source_trade_id: int | None = None):
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO lessons (category, lesson, source_trade_id) VALUES (?, ?, ?)",
            (category, lesson, source_trade_id),
        )
        conn.commit()

    def get_lessons(self, category: str | None = None) -> list[dict]:
        conn = self._conn()
        if category:
            rows = conn.execute("SELECT * FROM lessons WHERE category = ?", (category,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM lessons").fetchall()
        return [dict(r) for r in rows]

    def save_consolidated_rules(self, ruleset: str, feature_suggestions: str, lesson_count: int):
        """Save a new consolidated ruleset. History is retained."""
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO consolidated_rules (ruleset, feature_suggestions, lesson_count, consolidated_at) VALUES (?, ?, ?, ?)",
            (ruleset, feature_suggestions, lesson_count, now),
        )
        conn.commit()

    def get_latest_rules(self) -> dict | None:
        """Get the most recent consolidated ruleset."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM consolidated_rules ORDER BY consolidated_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def has_new_lessons_since_consolidation(self) -> bool:
        """Check if any lessons were created after the last consolidation."""
        conn = self._conn()
        lesson_count = conn.execute("SELECT COUNT(*) as n FROM lessons").fetchone()["n"]
        if lesson_count == 0:
            return False
        latest_rules = self.get_latest_rules()
        if latest_rules is None:
            return True  # Never consolidated, but lessons exist
        # Count-based check: lessons only grow (INSERT OR IGNORE deduplicates),
        # so if count > last consolidation's count, there are genuinely new lessons.
        return lesson_count > latest_rules["lesson_count"]

    def save_market_snapshots_batch(self, markets) -> int:
        """Persist a batch of ScannedMarket objects to market_snapshots."""
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                m.condition_id,
                m.question,
                m.yes_price,
                m.no_price,
                m.spread,
                m.liquidity,
                m.volume_24h,
                m.days_to_resolution,
                ",".join(str(f) for f in m.flags) if m.flags else "",
                m.scanned_at.isoformat() if m.scanned_at else now,
                getattr(m, "token_yes_id", None),
                getattr(m, "slug", None),
            )
            for m in markets
        ]
        conn.executemany(
            """INSERT INTO market_snapshots
               (condition_id, question, yes_price, no_price, spread, liquidity,
                volume_24h, days_to_resolution, flags, snapshot_at, token_yes_id, slug)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        return len(rows)

    def update_snapshot_token_id(self, condition_id: str, token_yes_id: str):
        """Update token_yes_id for all snapshots of a given conditionId."""
        conn = self._conn()
        conn.execute(
            "UPDATE market_snapshots SET token_yes_id = ? WHERE condition_id = ? AND token_yes_id IS NULL",
            (token_yes_id, condition_id),
        )
        conn.commit()

    def get_token_ids_for_conditions(self, condition_ids: set[str]) -> dict[str, str]:
        """Get mapping of conditionId -> token_yes_id from snapshots."""
        conn = self._conn()
        placeholders = ",".join("?" for _ in condition_ids)
        rows = conn.execute(
            f"""SELECT DISTINCT condition_id, token_yes_id
                FROM market_snapshots
                WHERE condition_id IN ({placeholders})
                  AND token_yes_id IS NOT NULL""",
            list(condition_ids),
        ).fetchall()
        return {r["condition_id"]: r["token_yes_id"] for r in rows}

    def get_pnl_history(self) -> list[dict]:
        """Daily PnL series with cumulative totals for charting."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT DATE(COALESCE(settled_at, resolved_at)) as date,
                      SUM(COALESCE(pnl, hypothetical_pnl)) as daily_pnl
               FROM trades
               WHERE status IN ('settled', 'dry_run_settled')
                 AND COALESCE(settled_at, resolved_at) IS NOT NULL
               GROUP BY DATE(COALESCE(settled_at, resolved_at))
               ORDER BY date"""
        ).fetchall()
        history = []
        cumulative = 0.0
        for row in rows:
            cumulative += row["daily_pnl"]
            history.append({
                "date": row["date"],
                "daily_pnl": row["daily_pnl"],
                "cumulative_pnl": round(cumulative, 2),
            })
        return history

    def get_recent_trades_with_names(self, limit: int = 20) -> list[dict]:
        """Get recent trades with market question resolved from snapshots."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT t.*, ms.question, ms.slug
               FROM trades t
               LEFT JOIN (
                   SELECT condition_id, question, slug,
                          ROW_NUMBER() OVER (PARTITION BY condition_id ORDER BY snapshot_at DESC) as rn
                   FROM market_snapshots
               ) ms ON t.market_id = ms.condition_id AND ms.rn = 1
               ORDER BY t.executed_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_daily_pnl(self) -> float:
        conn = self._conn()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE settled_at LIKE ? AND status = 'settled'",
            (f"{today}%",),
        ).fetchone()
        return row["total"]

    def get_trade_stats(self) -> dict:
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) as n FROM trades").fetchone()["n"]
        settled = conn.execute(
            "SELECT COUNT(*) as n FROM trades WHERE status IN ('settled', 'dry_run_settled')"
        ).fetchone()["n"]
        wins = conn.execute(
            "SELECT COUNT(*) as n FROM trades WHERE status IN ('settled', 'dry_run_settled') AND (pnl > 0 OR hypothetical_pnl > 0)"
        ).fetchone()["n"]
        total_pnl = conn.execute(
            "SELECT COALESCE(SUM(COALESCE(pnl, hypothetical_pnl, 0)), 0) as s FROM trades WHERE status IN ('settled', 'dry_run_settled')"
        ).fetchone()["s"]
        dry_run_pending = conn.execute(
            "SELECT COUNT(*) as n FROM trades WHERE status = 'dry_run'"
        ).fetchone()["n"]
        win_rate = (wins / settled) if settled > 0 else 0.0
        return {
            "total_trades": total,
            "settled_trades": settled,
            "dry_run_pending": dry_run_pending,
            "wins": wins,
            "losses": settled - wins,
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 2),
        }

    def get_snapshot_count(self) -> int:
        conn = self._conn()
        row = conn.execute("SELECT COUNT(*) as n FROM market_snapshots").fetchone()
        return row["n"]

    def save_prediction(self, market_id: str, question: str, market_yes_price: float,
                        predicted_prob: float, xgb_prob: float, llm_prob: float,
                        edge: float, confidence: float, recommended_side: str,
                        approved: bool, rejection_reason: str | None = None,
                        bet_size: float = 0, features_json: str | None = None):
        conn = self._conn()
        conn.execute(
            """INSERT INTO predictions
               (market_id, question, market_yes_price, predicted_prob, xgb_prob, llm_prob,
                edge, confidence, recommended_side, approved, rejection_reason, bet_size, features_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (market_id, question, market_yes_price, predicted_prob, xgb_prob, llm_prob,
             edge, confidence, recommended_side, 1 if approved else 0,
             rejection_reason, bet_size, features_json),
        )
        conn.commit()

    def get_prediction_stats(self) -> dict:
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]
        approved = conn.execute("SELECT COUNT(*) as n FROM predictions WHERE approved = 1").fetchone()["n"]
        blocked = total - approved
        avg_confidence = conn.execute(
            "SELECT COALESCE(AVG(confidence), 0) as v FROM predictions"
        ).fetchone()["v"]
        avg_edge = conn.execute(
            "SELECT COALESCE(AVG(ABS(edge)), 0) as v FROM predictions"
        ).fetchone()["v"]
        return {
            "total_predictions": total,
            "approved": approved,
            "blocked": blocked,
            "avg_confidence": round(avg_confidence, 4),
            "avg_edge": round(avg_edge, 4),
        }

    def get_prediction_accuracy(self) -> dict:
        """Compare predictions against resolved outcomes."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT p.market_id, p.recommended_side, p.predicted_prob, p.edge,
                      t.resolved_outcome, t.hypothetical_pnl
               FROM predictions p
               JOIN trades t ON p.market_id = t.market_id
               WHERE t.resolved_outcome IS NOT NULL AND p.approved = 1"""
        ).fetchall()
        if not rows:
            return {"evaluated": 0, "correct": 0, "accuracy": 0}
        correct = sum(1 for r in rows if r["recommended_side"] == r["resolved_outcome"])
        return {
            "evaluated": len(rows),
            "correct": correct,
            "accuracy": round(correct / len(rows), 4) if rows else 0,
        }

    def get_flagged_markets_with_predictions(self, limit: int = 30) -> list[dict]:
        """Get markets that have predictions, enriched with snapshot and trade data."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT p.market_id AS condition_id, p.question, p.market_yes_price AS yes_price,
                      p.recommended_side, p.edge, p.confidence, p.approved, p.rejection_reason,
                      p.predicted_at
               FROM predictions p
               INNER JOIN (
                   SELECT market_id, MAX(predicted_at) as max_at
                   FROM predictions
                   GROUP BY market_id
               ) latest ON p.market_id = latest.market_id AND p.predicted_at = latest.max_at
               ORDER BY p.predicted_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        markets = [dict(r) for r in rows]

        # Enrich with trade data and slug
        for m in markets:
            trade = conn.execute(
                "SELECT status, amount FROM trades WHERE market_id = ? ORDER BY executed_at DESC LIMIT 1",
                (m["condition_id"],),
            ).fetchone()
            if trade:
                m["trade_status"] = trade["status"]
                m["trade_amount"] = trade["amount"]
            slug_row = conn.execute(
                "SELECT slug FROM market_snapshots WHERE condition_id = ? AND slug IS NOT NULL ORDER BY snapshot_at DESC LIMIT 1",
                (m["condition_id"],),
            ).fetchone()
            m["slug"] = slug_row["slug"] if slug_row else None
        return markets

    def get_traded_market_ids(self) -> set[str]:
        """Return all market_ids that already have a trade (any status)."""
        conn = self._conn()
        rows = conn.execute("SELECT DISTINCT market_id FROM trades").fetchall()
        return {row["market_id"] for row in rows}

    def get_unresolved_dry_run_trades(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'dry_run' AND resolved_outcome IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def settle_dry_run_trade(self, trade_id: int, resolved_outcome: str, hypothetical_pnl: float):
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE trades SET status = 'dry_run_settled', resolved_outcome = ?, hypothetical_pnl = ?, resolved_at = ? WHERE id = ?",
            (resolved_outcome, hypothetical_pnl, now, trade_id),
        )
        conn.commit()

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

    def get_dry_run_trade_count(self) -> int:
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) as n FROM trades WHERE status IN ('dry_run', 'dry_run_settled')"
        ).fetchone()
        return row["n"]

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

    def get_latest_snapshot_price(self, condition_id: str) -> float | None:
        """Get the most recent YES price from market_snapshots for a given market."""
        conn = self._conn()
        row = conn.execute(
            "SELECT yes_price FROM market_snapshots WHERE condition_id = ? ORDER BY snapshot_at DESC LIMIT 1",
            (condition_id,),
        ).fetchone()
        return row["yes_price"] if row else None

    def save_pnl_snapshot(self, settled_pnl: float, unrealised_pnl: float,
                          total_pnl: float, open_positions: int,
                          win_rate: float | None = None, brier_score: float | None = None):
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO pnl_snapshots (settled_pnl, unrealised_pnl, total_pnl, open_positions, win_rate, brier_score, snapshot_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (settled_pnl, unrealised_pnl, total_pnl, open_positions, win_rate, brier_score, now),
        )
        conn.commit()

    def get_pnl_snapshots(self, limit: int = 500) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM pnl_snapshots ORDER BY snapshot_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------------------
    # Crypto read methods (tables created by the crypto bot — may not exist yet)
    # ---------------------------------------------------------------------------

    def _table_exists(self, table_name: str) -> bool:
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) as n FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row["n"] > 0

    def get_crypto_trade_stats(self) -> dict:
        if not self._table_exists("crypto_trades"):
            return {"total_trades": 0, "settled": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "total_pnl": 0.0}
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) as n FROM crypto_trades").fetchone()["n"]
        settled_statuses = ('won', 'lost', 'dry_run_won', 'dry_run_lost')
        ph = ",".join("?" for _ in settled_statuses)
        settled = conn.execute(f"SELECT COUNT(*) as n FROM crypto_trades WHERE status IN ({ph})", settled_statuses).fetchone()["n"]
        win_statuses = ('won', 'dry_run_won')
        wph = ",".join("?" for _ in win_statuses)
        wins = conn.execute(f"SELECT COUNT(*) as n FROM crypto_trades WHERE status IN ({wph})", win_statuses).fetchone()["n"]
        total_pnl = conn.execute(f"SELECT COALESCE(SUM(pnl), 0) as s FROM crypto_trades WHERE status IN ({ph})", settled_statuses).fetchone()["s"]
        return {
            "total_trades": total, "settled": settled, "wins": wins,
            "losses": settled - wins,
            "win_rate": round(wins / settled, 4) if settled > 0 else 0.0,
            "total_pnl": round(total_pnl, 2),
        }

    def get_recent_crypto_trades(self, limit: int = 50) -> list[dict]:
        if not self._table_exists("crypto_trades"):
            return []
        conn = self._conn()
        rows = conn.execute("SELECT * FROM crypto_trades ORDER BY placed_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_crypto_daily_pnl(self) -> float:
        """Sum of PnL for today's settled crypto trades."""
        if not self._table_exists("crypto_trades"):
            return 0.0
        conn = self._conn()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = conn.execute(
            """SELECT COALESCE(SUM(pnl), 0) as s FROM crypto_trades
               WHERE status IN ('won', 'lost', 'dry_run_won', 'dry_run_lost')
                 AND resolved_at LIKE ?""",
            (f"{today}%",),
        ).fetchone()
        return row["s"]

    def get_crypto_pnl_history(self) -> list[dict]:
        """Daily PnL history. Tries crypto_pnl_daily first, falls back to computing from trades."""
        if self._table_exists("crypto_pnl_daily"):
            conn = self._conn()
            rows = conn.execute("SELECT * FROM crypto_pnl_daily ORDER BY date ASC").fetchall()
            if rows:
                return [dict(r) for r in rows]
        # Fallback: compute from trades
        if not self._table_exists("crypto_trades"):
            return []
        conn = self._conn()
        rows = conn.execute(
            """SELECT DATE(resolved_at) as date,
                      COALESCE(SUM(pnl), 0) as daily_pnl
               FROM crypto_trades
               WHERE status IN ('won', 'lost', 'dry_run_won', 'dry_run_lost')
                 AND resolved_at IS NOT NULL
               GROUP BY DATE(resolved_at)
               ORDER BY date"""
        ).fetchall()
        history = []
        cumulative = 0.0
        for row in rows:
            cumulative += row["daily_pnl"]
            history.append({
                "date": row["date"],
                "net_pnl": round(row["daily_pnl"], 2),
                "cumulative_pnl": round(cumulative, 2),
            })
        return history

    def get_crypto_strategy_stats(self) -> list[dict]:
        if not self._table_exists("crypto_trades"):
            return []
        conn = self._conn()
        rows = conn.execute(
            """SELECT strategy,
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
                "strategy": r["strategy"], "total_trades": total,
                "wins": r["wins"], "losses": r["losses"],
                "win_rate": round(r["wins"] / total, 4) if total > 0 else 0.0,
                "total_pnl": round(r["total_pnl"], 2),
            })
        return result

    def get_all_incubations(self) -> list[dict]:
        if not self._table_exists("crypto_incubation"):
            return []
        conn = self._conn()
        rows = conn.execute("SELECT * FROM crypto_incubation ORDER BY strategy").fetchall()
        return [dict(r) for r in rows]

    def get_top_crypto_backtests(self, limit: int = 10) -> list[dict]:
        """Best backtest config per strategy (by expectancy), from the most recent run."""
        if not self._table_exists("crypto_backtests"):
            return []
        conn = self._conn()
        # All configs from the most recent backtest run (within 60s of the latest)
        rows = conn.execute(
            """SELECT * FROM crypto_backtests
               WHERE ran_at >= (
                   SELECT DATETIME(MAX(ran_at), '-60 seconds') FROM crypto_backtests
               )
               ORDER BY expectancy DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
