import sqlite3
import threading
from datetime import date, datetime, timezone


class Database:
    def __init__(self, path: str = "data/crypto.db"):
        self.path = path
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.path)
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA busy_timeout=30000")
        return self._local.connection

    def close(self):
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None

    def init(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS crypto_candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                UNIQUE(symbol, timestamp)
            );

            CREATE TABLE IF NOT EXISTS crypto_backtests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                params TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT DEFAULT '5m',
                total_trades INTEGER,
                win_rate REAL,
                expectancy REAL,
                total_pnl REAL,
                max_drawdown REAL,
                profit_factor REAL,
                sharpe REAL,
                ran_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS crypto_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                symbol TEXT NOT NULL,
                market_id TEXT,
                token_id TEXT,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                strike_price REAL,
                btc_price_at_entry REAL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'open',
                pnl REAL,
                signal_data TEXT,
                placed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME
            );

            CREATE TABLE IF NOT EXISTS crypto_incubation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL UNIQUE,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                position_size REAL DEFAULT 1.50,
                total_trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0.0,
                status TEXT DEFAULT 'incubating',
                last_updated DATETIME
            );

            CREATE TABLE IF NOT EXISTS crypto_pnl_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL UNIQUE,
                trades_count INTEGER,
                wins INTEGER,
                losses INTEGER,
                gross_pnl REAL,
                fees REAL,
                net_pnl REAL,
                cumulative_pnl REAL,
                bankroll_after REAL
            );

            CREATE INDEX IF NOT EXISTS idx_crypto_candles_symbol_ts
                ON crypto_candles(symbol, timestamp);
            CREATE INDEX IF NOT EXISTS idx_crypto_trades_status
                ON crypto_trades(status);
            CREATE INDEX IF NOT EXISTS idx_crypto_trades_placed_at
                ON crypto_trades(placed_at);
        """)
        conn.commit()

    # -------------------------------------------------------------------------
    # Trades
    # -------------------------------------------------------------------------

    def save_crypto_trade(
        self,
        strategy: str,
        symbol: str,
        market_id: str,
        side: str,
        entry_price: float,
        strike_price: float,
        btc_price_at_entry: float,
        amount: float,
        status: str,
        signal_data: str,
        token_id: str = None,
    ) -> int:
        conn = self._conn()
        cur = conn.execute(
            """
            INSERT INTO crypto_trades
                (strategy, symbol, market_id, token_id, side, entry_price,
                 strike_price, btc_price_at_entry, amount, status, signal_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (strategy, symbol, market_id, token_id, side, entry_price,
             strike_price, btc_price_at_entry, amount, status, signal_data),
        )
        conn.commit()
        return cur.lastrowid

    def get_open_crypto_trades(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM crypto_trades WHERE status IN ('open', 'dry_run_open') ORDER BY placed_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def settle_crypto_trade(
        self,
        trade_id: int,
        status: str,
        pnl: float,
        expected_status: str = None,
    ) -> bool:
        conn = self._conn()
        resolved_at = datetime.now(timezone.utc).isoformat()
        if expected_status is not None:
            cur = conn.execute(
                """
                UPDATE crypto_trades
                SET status = ?, pnl = ?, resolved_at = ?
                WHERE id = ? AND status = ?
                """,
                (status, pnl, resolved_at, trade_id, expected_status),
            )
        else:
            cur = conn.execute(
                """
                UPDATE crypto_trades
                SET status = ?, pnl = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, pnl, resolved_at, trade_id),
            )
        conn.commit()
        return cur.rowcount > 0

    def get_settled_crypto_trades(self, limit: int = 50) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT * FROM crypto_trades
            WHERE status IN ('won', 'lost', 'dry_run_won', 'dry_run_lost')
            ORDER BY resolved_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_crypto_trades(self, limit: int = 50) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM crypto_trades ORDER BY placed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_crypto_daily_pnl(self) -> float:
        conn = self._conn()
        today = date.today().isoformat()
        row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl), 0.0) AS total
            FROM crypto_trades
            WHERE status IN ('won', 'lost', 'dry_run_won', 'dry_run_lost')
              AND DATE(resolved_at) = ?
            """,
            (today,),
        ).fetchone()
        return row["total"] if row else 0.0

    def get_crypto_trade_stats(self) -> dict:
        conn = self._conn()
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_trades,
                SUM(CASE WHEN status IN ('won', 'lost', 'dry_run_won', 'dry_run_lost') THEN 1 ELSE 0 END) AS settled,
                SUM(CASE WHEN status IN ('won', 'dry_run_won') THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status IN ('lost', 'dry_run_lost') THEN 1 ELSE 0 END) AS losses,
                COALESCE(SUM(pnl), 0.0) AS total_pnl
            FROM crypto_trades
            """
        ).fetchone()
        total = row["total_trades"] or 0
        settled = row["settled"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        win_rate = (wins / settled) if settled > 0 else 0.0
        return {
            "total_trades": total,
            "settled": settled,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": row["total_pnl"],
        }

    def get_crypto_strategy_stats(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT
                strategy,
                COUNT(*) AS total_trades,
                SUM(CASE WHEN status IN ('won', 'dry_run_won') THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status IN ('lost', 'dry_run_lost') THEN 1 ELSE 0 END) AS losses,
                COALESCE(SUM(pnl), 0.0) AS total_pnl
            FROM crypto_trades
            WHERE status IN ('won', 'lost', 'dry_run_won', 'dry_run_lost')
            GROUP BY strategy
            ORDER BY total_pnl DESC
            """
        ).fetchall()
        result = []
        for r in rows:
            settled = (r["wins"] or 0) + (r["losses"] or 0)
            win_rate = (r["wins"] / settled) if settled > 0 else 0.0
            result.append({
                "strategy": r["strategy"],
                "total_trades": r["total_trades"],
                "wins": r["wins"],
                "losses": r["losses"],
                "win_rate": win_rate,
                "total_pnl": r["total_pnl"],
            })
        return result

    # -------------------------------------------------------------------------
    # Candles
    # -------------------------------------------------------------------------

    def save_crypto_candles(self, candles: list[dict]) -> None:
        conn = self._conn()
        conn.executemany(
            """
            INSERT OR REPLACE INTO crypto_candles
                (symbol, timestamp, open, high, low, close, volume)
            VALUES (:symbol, :timestamp, :open, :high, :low, :close, :volume)
            """,
            candles,
        )
        conn.commit()

    def get_crypto_candles(self, symbol: str, limit: int = 100) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT * FROM crypto_candles
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Backtests
    # -------------------------------------------------------------------------

    def save_crypto_backtest(
        self,
        strategy: str,
        params: str,
        symbol: str,
        total_trades: int,
        win_rate: float,
        expectancy: float,
        total_pnl: float,
        max_drawdown: float,
        profit_factor: float,
        sharpe: float,
        timeframe: str = "5m",
    ) -> int:
        conn = self._conn()
        cur = conn.execute(
            """
            INSERT INTO crypto_backtests
                (strategy, params, symbol, timeframe, total_trades, win_rate,
                 expectancy, total_pnl, max_drawdown, profit_factor, sharpe)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (strategy, params, symbol, timeframe, total_trades, win_rate,
             expectancy, total_pnl, max_drawdown, profit_factor, sharpe),
        )
        conn.commit()
        return cur.lastrowid

    def get_top_crypto_backtests(self, limit: int = 10) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT * FROM crypto_backtests
            ORDER BY expectancy DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # PnL Daily
    # -------------------------------------------------------------------------

    def upsert_crypto_pnl_daily(
        self,
        date: str,
        trades_count: int,
        wins: int,
        losses: int,
        gross_pnl: float,
        fees: float,
        net_pnl: float,
        bankroll: float,
    ) -> None:
        conn = self._conn()
        # Compute cumulative PnL = sum of all previous net_pnl + this net_pnl
        prior = conn.execute(
            "SELECT COALESCE(SUM(net_pnl), 0.0) FROM crypto_pnl_daily WHERE date < ?",
            (date,),
        ).fetchone()[0]
        cumulative_pnl = prior + net_pnl
        conn.execute(
            """
            INSERT INTO crypto_pnl_daily
                (date, trades_count, wins, losses, gross_pnl, fees, net_pnl,
                 cumulative_pnl, bankroll_after)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                trades_count = excluded.trades_count,
                wins = excluded.wins,
                losses = excluded.losses,
                gross_pnl = excluded.gross_pnl,
                fees = excluded.fees,
                net_pnl = excluded.net_pnl,
                cumulative_pnl = excluded.cumulative_pnl,
                bankroll_after = excluded.bankroll_after
            """,
            (date, trades_count, wins, losses, gross_pnl, fees, net_pnl,
             cumulative_pnl, bankroll),
        )
        conn.commit()

    def get_crypto_pnl_history(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM crypto_pnl_daily ORDER BY date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Incubation
    # -------------------------------------------------------------------------

    def get_or_create_incubation(self, strategy: str) -> dict:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM crypto_incubation WHERE strategy = ?", (strategy,)
        ).fetchone()
        if row is not None:
            return dict(row)
        conn.execute(
            "INSERT INTO crypto_incubation (strategy) VALUES (?)", (strategy,)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM crypto_incubation WHERE strategy = ?", (strategy,)
        ).fetchone()
        return dict(row)

    def update_incubation(
        self,
        strategy: str,
        total_trades: int,
        wins: int,
        losses: int,
        total_pnl: float,
        position_size: float = None,
        status: str = None,
    ) -> None:
        conn = self._conn()
        last_updated = datetime.now(timezone.utc).isoformat()
        if position_size is not None and status is not None:
            conn.execute(
                """
                UPDATE crypto_incubation
                SET total_trades = ?, wins = ?, losses = ?, total_pnl = ?,
                    position_size = ?, status = ?, last_updated = ?
                WHERE strategy = ?
                """,
                (total_trades, wins, losses, total_pnl, position_size, status,
                 last_updated, strategy),
            )
        elif position_size is not None:
            conn.execute(
                """
                UPDATE crypto_incubation
                SET total_trades = ?, wins = ?, losses = ?, total_pnl = ?,
                    position_size = ?, last_updated = ?
                WHERE strategy = ?
                """,
                (total_trades, wins, losses, total_pnl, position_size,
                 last_updated, strategy),
            )
        elif status is not None:
            conn.execute(
                """
                UPDATE crypto_incubation
                SET total_trades = ?, wins = ?, losses = ?, total_pnl = ?,
                    status = ?, last_updated = ?
                WHERE strategy = ?
                """,
                (total_trades, wins, losses, total_pnl, status,
                 last_updated, strategy),
            )
        else:
            conn.execute(
                """
                UPDATE crypto_incubation
                SET total_trades = ?, wins = ?, losses = ?, total_pnl = ?,
                    last_updated = ?
                WHERE strategy = ?
                """,
                (total_trades, wins, losses, total_pnl, last_updated, strategy),
            )
        conn.commit()

    def get_all_incubations(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM crypto_incubation ORDER BY started_at"
        ).fetchall()
        return [dict(r) for r in rows]
