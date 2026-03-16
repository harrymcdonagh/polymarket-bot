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
                predicted_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
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
        ]
        for col_name, col_type in migrations:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
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

    def update_trade_status(self, trade_id: int, status: str, pnl: float | None = None):
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        if pnl is not None:
            conn.execute(
                "UPDATE trades SET status = ?, pnl = ?, settled_at = ? WHERE id = ?",
                (status, pnl, now, trade_id),
            )
        else:
            conn.execute("UPDATE trades SET status = ? WHERE id = ?", (status, trade_id))
        conn.commit()

    def get_losing_trades(self, limit: int = 10) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'settled' AND pnl < 0 ORDER BY settled_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_lesson(self, category: str, lesson: str, source_trade_id: int | None = None):
        conn = self._conn()
        conn.execute(
            "INSERT INTO lessons (category, lesson, source_trade_id) VALUES (?, ?, ?)",
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

    def save_market_snapshots_batch(self, markets) -> None:
        """Persist a batch of ScannedMarket objects to market_snapshots."""
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            """INSERT INTO market_snapshots
               (condition_id, question, yes_price, no_price, spread, liquidity,
                volume_24h, days_to_resolution, flags, snapshot_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
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
                )
                for m in markets
            ],
        )
        conn.commit()

    def get_pnl_history(self) -> list[dict]:
        """Daily PnL series with cumulative totals for charting."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT DATE(settled_at) as date, SUM(pnl) as daily_pnl
               FROM trades WHERE status = 'settled' AND settled_at IS NOT NULL
               GROUP BY DATE(settled_at) ORDER BY date"""
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
            """SELECT t.*, ms.question
               FROM trades t
               LEFT JOIN (
                   SELECT condition_id, question,
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
                        bet_size: float = 0):
        conn = self._conn()
        conn.execute(
            """INSERT INTO predictions
               (market_id, question, market_yes_price, predicted_prob, xgb_prob, llm_prob,
                edge, confidence, recommended_side, approved, rejection_reason, bet_size)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (market_id, question, market_yes_price, predicted_prob, xgb_prob, llm_prob,
             edge, confidence, recommended_side, 1 if approved else 0,
             rejection_reason, bet_size),
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
        """Get flagged markets joined with their prediction outcome (if evaluated)."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT ms.condition_id, ms.question, ms.yes_price, ms.flags, ms.snapshot_at,
                      p.recommended_side, p.edge, p.confidence, p.approved, p.rejection_reason,
                      t.status as trade_status, t.amount as trade_amount
               FROM market_snapshots ms
               LEFT JOIN (
                   SELECT market_id, recommended_side, edge, confidence, approved, rejection_reason,
                          ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY predicted_at DESC) as rn
                   FROM predictions
               ) p ON ms.condition_id = p.market_id AND p.rn = 1
               LEFT JOIN (
                   SELECT market_id, status, amount,
                          ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY executed_at DESC) as rn
                   FROM trades
               ) t ON ms.condition_id = t.market_id AND t.rn = 1
               WHERE ms.flags != '' AND ms.flags IS NOT NULL
               GROUP BY ms.condition_id
               ORDER BY ms.snapshot_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

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

    def get_dry_run_trade_count(self) -> int:
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) as n FROM trades WHERE status IN ('dry_run', 'dry_run_settled')"
        ).fetchone()
        return row["n"]
