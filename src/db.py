import sqlite3
from datetime import datetime, timezone


class Database:
    def __init__(self, path: str = "bot.db"):
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

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
        """)
        conn.commit()
        conn.close()

    def save_trade(self, market_id: str, side: str, amount: float, price: float, order_id: str | None = None):
        conn = self._conn()
        conn.execute(
            "INSERT INTO trades (market_id, side, amount, price, order_id) VALUES (?, ?, ?, ?, ?)",
            (market_id, side, amount, price, order_id),
        )
        conn.commit()
        conn.close()

    def get_open_trades(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute("SELECT * FROM trades WHERE status = 'pending'").fetchall()
        conn.close()
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
        conn.close()

    def get_losing_trades(self, limit: int = 10) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'settled' AND pnl < 0 ORDER BY settled_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def save_lesson(self, category: str, lesson: str, source_trade_id: int | None = None):
        conn = self._conn()
        conn.execute(
            "INSERT INTO lessons (category, lesson, source_trade_id) VALUES (?, ?, ?)",
            (category, lesson, source_trade_id),
        )
        conn.commit()
        conn.close()

    def get_lessons(self, category: str | None = None) -> list[dict]:
        conn = self._conn()
        if category:
            rows = conn.execute("SELECT * FROM lessons WHERE category = ?", (category,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM lessons").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_daily_pnl(self) -> float:
        conn = self._conn()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE settled_at LIKE ? AND status = 'settled'",
            (f"{today}%",),
        ).fetchone()
        conn.close()
        return row["total"]
