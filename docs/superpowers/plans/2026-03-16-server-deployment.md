# Server Deployment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the polymarket bot to a DigitalOcean droplet for 24/7 unattended dry-run operation with Telegram notifications, settlement monitoring, and a web dashboard.

**Architecture:** Three systemd services (bot loop, web dashboard, settlement monitor) share a SQLite database via WAL mode. A Telegram module sends alerts on key events. HTTP Basic Auth protects the dashboard.

**Tech Stack:** Python 3.11+, systemd, SQLite WAL, Telegram Bot API (httpx), FastAPI Basic Auth, Ubuntu 24.04

**Spec:** `docs/superpowers/specs/2026-03-16-server-deployment-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|---|---|
| `src/notifications/__init__.py` | Package init |
| `src/notifications/telegram.py` | Telegram Bot API client — format and send messages for trade alerts, errors, daily summaries |
| `src/settler/__init__.py` | Package init |
| `src/settler/settler.py` | Settlement monitor — check dry-run trade resolution, calculate hypothetical P&L, trigger postmortem |
| `deploy/polymarket-bot.service` | Systemd unit for main bot loop |
| `deploy/polymarket-web.service` | Systemd unit for web dashboard |
| `deploy/polymarket-settler.service` | Systemd unit for settlement monitor |
| `deploy/setup.sh` | Server provisioning script |

### Modified Files
| File | Change |
|---|---|
| `src/config.py` | Add `DB_PATH`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DASHBOARD_PASSWORD` |
| `src/db.py` | WAL mode, busy_timeout, `migrate()`, settlement columns + queries |
| `src/pipeline.py` | Store `predicted_prob` in dry-run trades, integrate Telegram notifications |
| `src/dashboard/web.py` | HTTP Basic Auth middleware |
| `run.py` | `--settle` flag, `--host` flag, wire `DB_PATH` |
| `.env.example` | Telegram and dashboard config |

### Test Files
| File | Coverage |
|---|---|
| `tests/test_db_migration.py` | Migration adds columns, WAL mode, idempotent |
| `tests/test_telegram.py` | Message formatting, send (mocked HTTP) |
| `tests/test_settler.py` | Settlement detection, P&L calculation, postmortem trigger |
| `tests/test_web_auth.py` | Basic Auth blocks/allows requests |

---

## Chunk 1: Database & Config Foundation

### Task 1: Add new config settings

**Files:**
- Modify: `src/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add settings to config.py**

Add after the `LOOP_INTERVAL` line in `src/config.py`:

```python
    # Database
    DB_PATH: str = "data/polymarket.db"

    # Telegram notifications
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Dashboard security
    DASHBOARD_PASSWORD: str = ""
```

- [ ] **Step 2: Update .env.example**

Add at the end of `.env.example`:

```
# Database path (relative to working directory)
DB_PATH=data/polymarket.db

# Telegram notifications (create bot via @BotFather)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Dashboard password (leave empty to disable auth)
DASHBOARD_PASSWORD=
```

- [ ] **Step 3: Verify settings load**

Run: `python -c "from src.config import Settings; s = Settings(); print(s.DB_PATH, s.TELEGRAM_BOT_TOKEN, s.DASHBOARD_PASSWORD)"`
Expected: `data/polymarket.db  ` (empty strings for tokens)

- [ ] **Step 4: Commit**

```bash
git add src/config.py .env.example
git commit -m "feat: add DB_PATH, Telegram, and dashboard auth settings"
```

---

### Task 2: Database WAL mode, busy_timeout, and migration

**Files:**
- Modify: `src/db.py`
- Create: `tests/test_db_migration.py`

- [ ] **Step 1: Write failing test for WAL mode and migration**

Create `tests/test_db_migration.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_migration.py -v`
Expected: FAIL (no `migrate`, no WAL, no new columns)

- [ ] **Step 3: Implement WAL mode and busy_timeout in `_conn()`**

In `src/db.py`, update the `_conn` method:

```python
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.path)
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA busy_timeout=30000")
        return self._local.connection
```

- [ ] **Step 4: Add `migrate()` method and call from `init()`**

Add after `init()` in `src/db.py`:

```python
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
```

Call `self.migrate()` at the end of `init()`.

- [ ] **Step 5: Update `save_trade()` to accept `predicted_prob`**

```python
    def save_trade(self, market_id: str, side: str, amount: float, price: float,
                   order_id: str | None = None, status: str = "pending",
                   predicted_prob: float | None = None):
        conn = self._conn()
        conn.execute(
            "INSERT INTO trades (market_id, side, amount, price, order_id, status, predicted_prob) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (market_id, side, amount, price, order_id, status, predicted_prob),
        )
        conn.commit()
```

- [ ] **Step 6: Add settlement query methods**

```python
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
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_migration.py -v`
Expected: All 6 tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/db.py tests/test_db_migration.py
git commit -m "feat: add WAL mode, migration system, and settlement columns to database"
```

---

### Task 3: Wire DB_PATH through pipeline and run.py

**Files:**
- Modify: `src/pipeline.py`
- Modify: `run.py`

- [ ] **Step 1: Update Pipeline to use settings.DB_PATH**

In `src/pipeline.py`, change the `__init__` signature and body:

```python
    def __init__(self, settings: Settings | None = None, db_path: str | None = None,
                 status_callback=None):
        self.settings = settings or Settings()
        self._status_callback = status_callback
        self.db = Database(db_path or self.settings.DB_PATH)
        self.db.init()
```

Remove the `db_path: str = "bot.db"` default parameter.

- [ ] **Step 2: Update `run.py` to pass DB_PATH**

In `run.py`, no explicit `db_path` needed since Pipeline reads from settings. But ensure the `data/` directory exists:

```python
def main():
    settings = Settings()

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("polymarket-bot")

    # Ensure data directory exists
    import os
    os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)
```

- [ ] **Step 3: Update web.py create_app to use settings.DB_PATH**

In `src/dashboard/web.py`, add import for `Settings` and change `create_app`:

```python
from src.config import Settings
```

```python
def create_app(settings=None, db_path: str | None = None) -> FastAPI:
    settings = settings or Settings()
    service = DashboardService(settings=settings, db_path=db_path or settings.DB_PATH)
```

- [ ] **Step 4: Verify bot starts**

Run: `python -c "from src.config import Settings; from src.pipeline import Pipeline; p = Pipeline(Settings()); print('OK')"`
Expected: `OK` (and `data/polymarket.db` is created)

- [ ] **Step 5: Commit**

```bash
git add src/pipeline.py run.py src/dashboard/web.py
git commit -m "feat: wire DB_PATH config through pipeline and dashboard"
```

---

## Chunk 2: Telegram Notifications

### Task 4: Telegram notification module

**Files:**
- Create: `src/notifications/__init__.py`
- Create: `src/notifications/telegram.py`
- Create: `tests/test_telegram.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_telegram.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from src.notifications.telegram import TelegramNotifier


@pytest.fixture
def notifier():
    return TelegramNotifier(bot_token="test-token", chat_id="12345")


@pytest.fixture
def disabled_notifier():
    return TelegramNotifier(bot_token="", chat_id="")


def test_is_enabled(notifier):
    assert notifier.is_enabled is True


def test_is_disabled_when_no_token(disabled_notifier):
    assert disabled_notifier.is_enabled is False


def test_format_trade_alert(notifier):
    msg = notifier.format_trade_alert(
        question="Will X happen?",
        side="YES",
        amount=10.0,
        price=0.42,
        edge=0.12,
    )
    assert "Will X happen?" in msg
    assert "YES" in msg
    assert "$10.00" in msg
    assert "12.0%" in msg


def test_format_settlement_alert(notifier):
    msg = notifier.format_settlement_alert(
        question="Will X happen?",
        outcome="YES",
        predicted_prob=0.72,
        price=0.42,
        pnl=5.0,
    )
    assert "Will X happen?" in msg
    assert "YES" in msg
    assert "+$5.00" in msg


def test_format_error_alert(notifier):
    msg = notifier.format_error_alert("Research pipeline failed: timeout")
    assert "timeout" in msg


def test_format_daily_summary(notifier):
    msg = notifier.format_daily_summary(
        markets_scanned=50,
        trades_flagged=3,
        top_edge=0.15,
        top_market="Will Y happen?",
    )
    assert "50" in msg
    assert "3" in msg


@pytest.mark.asyncio
async def test_send_skips_when_disabled(disabled_notifier):
    # Should not raise or make any HTTP call
    await disabled_notifier.send("test message")


@pytest.mark.asyncio
async def test_send_calls_telegram_api(notifier):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notifier.send("Hello world")
        mock_client.post.assert_called_once()
        call_url = mock_client.post.call_args[0][0]
        assert "test-token" in call_url
        assert "sendMessage" in call_url
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Create package init**

Create `src/notifications/__init__.py` (empty file).

- [ ] **Step 4: Implement TelegramNotifier**

Create `src/notifications/telegram.py`:

```python
import logging
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def is_enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(self, text: str) -> None:
        if not self.is_enabled:
            return
        url = TELEGRAM_API.format(token=self.bot_token)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                })
                if resp.status_code != 200:
                    logger.warning(f"Telegram send failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.warning(f"Telegram send error: {e}")

    def format_trade_alert(self, question: str, side: str, amount: float,
                           price: float, edge: float) -> str:
        return (
            f"*Dry-Run Trade*\n"
            f"Market: {question}\n"
            f"Side: {side} @ ${price:.2f}\n"
            f"Amount: ${amount:.2f}\n"
            f"Edge: {edge:.1%}"
        )

    def format_settlement_alert(self, question: str, outcome: str,
                                predicted_prob: float, price: float,
                                pnl: float) -> str:
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        return (
            f"*Market Resolved*\n"
            f"Market: {question}\n"
            f"Outcome: {outcome}\n"
            f"Prediction: {predicted_prob:.0%} @ ${price:.2f}\n"
            f"Hypothetical P&L: {pnl_str}"
        )

    def format_error_alert(self, error: str) -> str:
        return f"*Pipeline Error*\n{error}"

    def format_daily_summary(self, markets_scanned: int, trades_flagged: int,
                             top_edge: float, top_market: str) -> str:
        return (
            f"*Daily Summary*\n"
            f"Markets scanned: {markets_scanned}\n"
            f"Trades flagged: {trades_flagged}\n"
            f"Top edge: {top_edge:.1%} on {top_market}"
        )

    def format_startup(self) -> str:
        return "*Bot Started*\nPolymarket bot is online."
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/notifications/ tests/test_telegram.py
git commit -m "feat: add Telegram notification module"
```

---

### Task 5: Integrate Telegram into pipeline

**Files:**
- Modify: `src/pipeline.py`
- Modify: `run.py`

- [ ] **Step 1: Add TelegramNotifier to Pipeline.__init__**

In `src/pipeline.py`, add import and init:

```python
from src.notifications.telegram import TelegramNotifier
```

At end of `__init__`:

```python
        self.notifier = TelegramNotifier(
            bot_token=self.settings.TELEGRAM_BOT_TOKEN,
            chat_id=self.settings.TELEGRAM_CHAT_ID,
        )
```

- [ ] **Step 2: Send notification on dry-run trade**

In `run_cycle()`, after the `self.dry_run_trades.append(...)` block (around line 266), add:

```python
                    if self.notifier.is_enabled:
                        msg = self.notifier.format_trade_alert(
                            question=market.question,
                            side=prediction.recommended_side,
                            amount=decision.bet_size_usd,
                            price=market.yes_price,
                            edge=prediction.edge,
                        )
                        await self.notifier.send(msg)
```

- [ ] **Step 3: Send notification on pipeline error**

In the `except` block of the market loop (around line 268), add:

```python
                if self.notifier.is_enabled:
                    await self.notifier.send(
                        self.notifier.format_error_alert(f"{market.question[:50]}: {e}")
                    )
```

- [ ] **Step 4: Store predicted_prob in dry-run trade save**

Update the `save_trade` call in the dry-run block:

```python
                    self.db.save_trade(
                        market_id=market.condition_id,
                        side=prediction.recommended_side,
                        amount=decision.bet_size_usd,
                        price=market.yes_price,
                        order_id=None,
                        status="dry_run",
                        predicted_prob=prediction.predicted_probability,
                    )
```

- [ ] **Step 5: Send startup notification in the loop function**

In `run.py`, update `_loop` to send a startup notification at the beginning:

```python
async def _loop(pipeline, dry_run: bool, interval: int):
    logger = logging.getLogger("polymarket-bot")
    if pipeline.notifier.is_enabled:
        await pipeline.notifier.send(pipeline.notifier.format_startup())
    while True:
        try:
            await pipeline.run_cycle(dry_run=dry_run)
        except Exception as e:
            logger.error(f"Cycle failed: {e}")
        logger.info(f"Sleeping {interval}s until next cycle...")
        await asyncio.sleep(interval)
```

- [ ] **Step 6: Verify bot still starts**

Run: `python run.py --help 2>&1 || python -c "from src.pipeline import Pipeline; print('OK')"`
Expected: No import errors

- [ ] **Step 7: Commit**

```bash
git add src/pipeline.py run.py
git commit -m "feat: integrate Telegram notifications into pipeline"
```

---

## Chunk 3: Settlement Monitor

### Task 6: Settlement monitor module

**Files:**
- Create: `src/settler/__init__.py`
- Create: `src/settler/settler.py`
- Create: `tests/test_settler.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_settler.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.settler.settler import Settler
from src.db import Database


@pytest.fixture
def tmp_db(tmp_path):
    db = Database(path=str(tmp_path / "test.db"))
    db.init()
    return db


@pytest.fixture
def settler(tmp_db):
    notifier = MagicMock()
    notifier.is_enabled = False
    return Settler(db=tmp_db, notifier=notifier, gamma_url="https://gamma-api.polymarket.com")


def test_calc_hypothetical_pnl_win_yes(settler):
    # Bought YES at $0.40 for $10. Market resolved YES.
    # Shares = 10 / 0.40 = 25. Payout = 25 * 1.0 = 25. PnL = 25 - 10 = 15
    pnl = settler.calc_hypothetical_pnl(side="YES", amount=10.0, price=0.40, outcome="YES")
    assert pnl == pytest.approx(15.0)


def test_calc_hypothetical_pnl_loss_yes(settler):
    # Bought YES at $0.40 for $10. Market resolved NO.
    # Shares worth $0. PnL = 0 - 10 = -10
    pnl = settler.calc_hypothetical_pnl(side="YES", amount=10.0, price=0.40, outcome="NO")
    assert pnl == pytest.approx(-10.0)


def test_calc_hypothetical_pnl_win_no(settler):
    # Bought NO. yes_price=0.60, so NO price = 0.40. Amount=$10.
    # Shares = 10 / 0.40 = 25. Payout = 25. PnL = 25 - 10 = 15
    pnl = settler.calc_hypothetical_pnl(side="NO", amount=10.0, price=0.60, outcome="NO")
    assert pnl == pytest.approx(15.0)


def test_calc_hypothetical_pnl_loss_no(settler):
    # Bought NO at $0.60 for $10. Market resolved YES.
    pnl = settler.calc_hypothetical_pnl(side="NO", amount=10.0, price=0.60, outcome="YES")
    assert pnl == pytest.approx(-10.0)


@pytest.mark.asyncio
async def test_check_resolution_returns_none_for_active(settler):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"closed": False, "resolved": False}

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        result = await settler.check_resolution("condition-123")
        assert result is None


@pytest.mark.asyncio
async def test_check_resolution_returns_outcome(settler):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True,
        "resolved": True,
        "outcomePrices": "[\"1\",\"0\"]",
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        result = await settler.check_resolution("condition-123")
        assert result == "YES"


@pytest.mark.asyncio
async def test_run_settles_resolved_trades(settler, tmp_db):
    tmp_db.save_trade("cond-1", "YES", 10.0, 0.5, status="dry_run", predicted_prob=0.7)

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "closed": True, "resolved": True, "outcomePrices": "[\"1\",\"0\"]"
    }

    settler.postmortem = AsyncMock()
    settler.postmortem.analyze_loss = AsyncMock(return_value={})

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        await settler.run()

    trades = tmp_db.get_unresolved_dry_run_trades()
    assert len(trades) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settler.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Create package init**

Create `src/settler/__init__.py` (empty file).

- [ ] **Step 4: Implement Settler**

Create `src/settler/settler.py`:

```python
import json
import logging
from datetime import datetime, timezone
import httpx
from src.db import Database
from src.notifications.telegram import TelegramNotifier
from src.postmortem.postmortem import PostmortemAnalyzer

logger = logging.getLogger(__name__)


class Settler:
    def __init__(self, db: Database, notifier: TelegramNotifier,
                 gamma_url: str = "https://gamma-api.polymarket.com",
                 postmortem: PostmortemAnalyzer | None = None):
        self.db = db
        self.notifier = notifier
        self.gamma_url = gamma_url
        self.postmortem = postmortem
        self._last_summary_date: str | None = None

    async def check_resolution(self, condition_id: str) -> str | None:
        """Check if a market has resolved. Returns 'YES'/'NO' or None if still active."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{self.gamma_url}/markets/{condition_id}")
                if resp.status_code != 200:
                    logger.warning(f"Gamma API returned {resp.status_code} for {condition_id}")
                    return None
                data = resp.json()

            if not data.get("resolved", False):
                return None

            prices_str = data.get("outcomePrices", "[]")
            prices = json.loads(prices_str)
            if len(prices) >= 2:
                yes_price = float(prices[0])
                return "YES" if yes_price > 0.5 else "NO"
            return None
        except Exception as e:
            logger.warning(f"Resolution check failed for {condition_id}: {e}")
            return None

    def calc_hypothetical_pnl(self, side: str, amount: float, price: float,
                              outcome: str) -> float:
        """Calculate what the P&L would have been.

        On Polymarket, buying shares at price P means you get (amount/P) shares.
        If your side wins, each share pays $1. If it loses, shares are worth $0.
        """
        if side == "YES":
            shares = amount / price
            if outcome == "YES":
                return shares * 1.0 - amount  # profit
            else:
                return -amount  # total loss
        else:  # NO
            no_price = price  # price stored is yes_price; NO price = 1 - yes_price
            # But we stored the yes_price, and side is NO
            # For NO trades, the buy price for NO shares = 1 - yes_price
            # Actually, in the current code, `price` is `market.yes_price`
            # and side is NO. So NO share price = 1 - price
            no_share_price = 1.0 - price
            shares = amount / no_share_price
            if outcome == "NO":
                return shares * 1.0 - amount
            else:
                return -amount

    async def run(self) -> None:
        """Check all unresolved dry-run trades and settle any that have resolved."""
        trades = self.db.get_unresolved_dry_run_trades()
        if not trades:
            logger.info("No unresolved dry-run trades to check")
            return

        logger.info(f"Checking {len(trades)} unresolved dry-run trades")

        for trade in trades:
            outcome = await self.check_resolution(trade["market_id"])
            if outcome is None:
                continue

            pnl = self.calc_hypothetical_pnl(
                side=trade["side"],
                amount=trade["amount"],
                price=trade["price"],
                outcome=outcome,
            )

            self.db.settle_dry_run_trade(
                trade_id=trade["id"],
                resolved_outcome=outcome,
                hypothetical_pnl=pnl,
            )

            logger.info(
                f"Settled: {trade['market_id'][:20]} → {outcome} | "
                f"Hypothetical P&L: ${pnl:.2f}"
            )

            # Run postmortem on losses
            if pnl < 0 and self.postmortem:
                try:
                    await self.postmortem.analyze_loss(
                        question=trade["market_id"],
                        predicted_prob=trade.get("predicted_prob", 0.5),
                        actual_outcome=outcome,
                        pnl=pnl,
                        reasoning="Dry-run trade — see trade history",
                    )
                except Exception as e:
                    logger.error(f"Postmortem failed for trade {trade['id']}: {e}")

            # Notify
            if self.notifier.is_enabled:
                msg = self.notifier.format_settlement_alert(
                    question=trade["market_id"],
                    outcome=outcome,
                    predicted_prob=trade.get("predicted_prob", 0.5),
                    price=trade["price"],
                    pnl=pnl,
                )
                await self.notifier.send(msg)

        await self._maybe_send_daily_summary()

    async def _maybe_send_daily_summary(self) -> None:
        """Send daily summary if it hasn't been sent today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_summary_date == today:
            return
        if not self.notifier.is_enabled:
            return

        stats = self.db.get_trade_stats()
        dry_run_count = self.db.get_dry_run_trade_count()

        msg = (
            f"*Daily Summary ({today})*\n"
            f"Dry-run trades: {dry_run_count}\n"
            f"Settled: {stats['total_trades']} | Win rate: {stats['win_rate']:.0%}\n"
            f"Total P&L: ${stats['total_pnl']:.2f}"
        )
        await self.notifier.send(msg)
        self._last_summary_date = today
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_settler.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/settler/ tests/test_settler.py
git commit -m "feat: add settlement monitor for dry-run trade resolution"
```

---

### Task 7: Add --settle flag to run.py

**Files:**
- Modify: `run.py`

- [ ] **Step 1: Add settle mode to run.py**

Add after the `--web` block and before the `dry_run = "--live" not in sys.argv` line:

```python
    if "--settle" in sys.argv:
        from src.settler.settler import Settler
        from src.notifications.telegram import TelegramNotifier
        from src.db import Database
        from src.postmortem.postmortem import PostmortemAnalyzer
        import os

        os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)
        db = Database(settings.DB_PATH)
        db.init()
        notifier = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
        postmortem = PostmortemAnalyzer(settings=settings, db=db)
        settler = Settler(db=db, notifier=notifier, postmortem=postmortem,
                          gamma_url=settings.POLYMARKET_GAMMA_URL)

        interval = 3600
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])

        logger.info(f"=== SETTLEMENT MONITOR: checking every {interval}s ===")
        asyncio.run(_settle_loop(settler, interval))
        return
```

Add the settle loop function:

```python
async def _settle_loop(settler, interval: int):
    logger = logging.getLogger("polymarket-bot")
    while True:
        try:
            await settler.run()
        except Exception as e:
            logger.error(f"Settlement cycle failed: {e}")
        logger.info(f"Sleeping {interval}s until next settlement check...")
        await asyncio.sleep(interval)
```

- [ ] **Step 2: Verify it starts**

Run: `python run.py --settle --interval=5 &` then kill after a few seconds.
Expected: Logs "SETTLEMENT MONITOR: checking every 5s" and "No unresolved dry-run trades"

- [ ] **Step 3: Commit**

```bash
git add run.py
git commit -m "feat: add --settle flag for settlement monitor loop"
```

---

## Chunk 4: Dashboard Auth & Web Host

### Task 8: Dashboard HTTP Basic Auth

**Files:**
- Modify: `src/dashboard/web.py`
- Create: `tests/test_web_auth.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_web_auth.py`:

```python
import base64
import pytest
from fastapi.testclient import TestClient
from src.config import Settings
from src.dashboard.web import create_app


@pytest.fixture
def app_with_auth(tmp_path):
    settings = Settings(DASHBOARD_PASSWORD="secret123", DB_PATH=str(tmp_path / "test.db"))
    app = create_app(settings=settings)
    return app


@pytest.fixture
def app_no_auth(tmp_path):
    settings = Settings(DASHBOARD_PASSWORD="", DB_PATH=str(tmp_path / "test.db"))
    app = create_app(settings=settings)
    return app


def test_auth_required_blocks_unauthenticated(app_with_auth):
    client = TestClient(app_with_auth)
    resp = client.get("/")
    assert resp.status_code == 401


def test_auth_required_allows_correct_password(app_with_auth):
    client = TestClient(app_with_auth)
    creds = base64.b64encode(b"admin:secret123").decode()
    resp = client.get("/", headers={"Authorization": f"Basic {creds}"})
    assert resp.status_code == 200


def test_auth_required_rejects_wrong_password(app_with_auth):
    client = TestClient(app_with_auth)
    creds = base64.b64encode(b"admin:wrong").decode()
    resp = client.get("/", headers={"Authorization": f"Basic {creds}"})
    assert resp.status_code == 401


def test_no_auth_when_password_empty(app_no_auth):
    client = TestClient(app_no_auth)
    resp = client.get("/")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_auth.py -v`
Expected: FAIL (no auth middleware)

- [ ] **Step 3: Add Basic Auth middleware to web.py**

In `src/dashboard/web.py`, add imports:

```python
import base64
import secrets
from fastapi.responses import Response
```

Inside `create_app`, after `app = FastAPI(...)` and before the static mount:

```python
    password = settings.DASHBOARD_PASSWORD if settings else ""

    if password:
        @app.middleware("http")
        async def basic_auth(request: Request, call_next):
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth[6:]).decode()
                    _, pwd = decoded.split(":", 1)
                    if secrets.compare_digest(pwd, password):
                        return await call_next(request)
                except Exception:
                    pass
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": "Basic realm=\"Polymarket Bot\""},
                content="Unauthorized",
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_auth.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/web.py tests/test_web_auth.py
git commit -m "feat: add HTTP Basic Auth to web dashboard"
```

---

### Task 9: Add --host flag to run.py

**Files:**
- Modify: `run.py`

- [ ] **Step 1: Add --host parsing to web section**

In `run.py`, update the `--web` block:

```python
    if "--web" in sys.argv:
        from src.dashboard.web import create_app
        import uvicorn
        import os

        os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)

        host = "127.0.0.1"
        for arg in sys.argv:
            if arg.startswith("--host="):
                host = arg.split("=")[1]

        fastapi_app = create_app(settings=settings)
        fastapi_app.state.service.dry_run = "--live" not in sys.argv
        logger.info(f"Starting web dashboard on http://{host}:8050")
        uvicorn.run(fastapi_app, host=host, port=8050, log_level=settings.LOG_LEVEL.lower())
        return
```

- [ ] **Step 2: Commit**

```bash
git add run.py
git commit -m "feat: add --host flag for web dashboard binding"
```

---

## Chunk 5: Deploy Files

### Task 10: Systemd service files

**Files:**
- Create: `deploy/polymarket-bot.service`
- Create: `deploy/polymarket-web.service`
- Create: `deploy/polymarket-settler.service`

- [ ] **Step 1: Create deploy directory**

Run: `mkdir -p deploy`

- [ ] **Step 2: Create polymarket-bot.service**

```ini
[Unit]
Description=Polymarket Bot - Trading Loop
After=network.target

[Service]
Type=simple
User=polymarket
Group=polymarket
WorkingDirectory=/opt/polymarket-bot
EnvironmentFile=/opt/polymarket-bot/.env
ExecStart=/opt/polymarket-bot/venv/bin/python run.py --loop --interval=600
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Create polymarket-web.service**

```ini
[Unit]
Description=Polymarket Bot - Web Dashboard
After=network.target

[Service]
Type=simple
User=polymarket
Group=polymarket
WorkingDirectory=/opt/polymarket-bot
EnvironmentFile=/opt/polymarket-bot/.env
ExecStart=/opt/polymarket-bot/venv/bin/python run.py --web --host=0.0.0.0
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Create polymarket-settler.service**

```ini
[Unit]
Description=Polymarket Bot - Settlement Monitor
After=network.target

[Service]
Type=simple
User=polymarket
Group=polymarket
WorkingDirectory=/opt/polymarket-bot
EnvironmentFile=/opt/polymarket-bot/.env
ExecStart=/opt/polymarket-bot/venv/bin/python run.py --settle --interval=3600
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 5: Commit**

```bash
git add deploy/
git commit -m "feat: add systemd service files for bot, web, and settler"
```

---

### Task 11: Server setup script

**Files:**
- Create: `deploy/setup.sh`

- [ ] **Step 1: Create setup.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Polymarket Bot - Server Setup Script
# Run as root on a fresh Ubuntu 24.04 droplet

APP_DIR="/opt/polymarket-bot"
APP_USER="polymarket"

echo "=== Installing system packages ==="
apt-get update
apt-get install -y python3 python3-venv python3-pip git ufw sqlite3

echo "=== Creating $APP_USER user ==="
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "$APP_USER"
fi

echo "=== Cloning repository ==="
if [ ! -d "$APP_DIR" ]; then
    git clone https://github.com/YOUR_USERNAME/polymarket-bot.git "$APP_DIR"
else
    cd "$APP_DIR" && git pull
fi
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "=== Setting up Python virtual environment ==="
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -e "$APP_DIR"

echo "=== Creating data directory ==="
sudo -u "$APP_USER" mkdir -p "$APP_DIR/data"

echo "=== Setting up .env ==="
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chown "$APP_USER":"$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    echo ">>> EDIT $APP_DIR/.env with your API keys <<<"
fi

echo "=== Installing systemd services ==="
cp "$APP_DIR/deploy/polymarket-bot.service" /etc/systemd/system/
cp "$APP_DIR/deploy/polymarket-web.service" /etc/systemd/system/
cp "$APP_DIR/deploy/polymarket-settler.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable polymarket-bot polymarket-web polymarket-settler

echo "=== Configuring firewall ==="
ufw allow OpenSSH
ufw allow 8050/tcp
ufw --force enable

echo "=== Configuring journald log retention ==="
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/polymarket.conf << 'CONF'
[Journal]
SystemMaxUse=500M
CONF
systemctl restart systemd-journald

echo "=== Setting up daily backup cron ==="
cat > /etc/cron.daily/polymarket-backup << 'CRON'
#!/bin/bash
sqlite3 /opt/polymarket-bot/data/polymarket.db ".backup /opt/polymarket-bot/data/backup-$(date +%Y%m%d).db"
chown polymarket:polymarket /opt/polymarket-bot/data/backup-*.db
find /opt/polymarket-bot/data/ -name "backup-*.db" -mtime +7 -delete
CRON
chmod +x /etc/cron.daily/polymarket-backup

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit /opt/polymarket-bot/.env with your API keys"
echo "  2. Start services:"
echo "     sudo systemctl start polymarket-bot polymarket-web polymarket-settler"
echo "  3. Check status:"
echo "     sudo systemctl status polymarket-bot"
echo "  4. View logs:"
echo "     journalctl -u polymarket-bot -f"
```

- [ ] **Step 2: Make executable**

Run: `chmod +x deploy/setup.sh`

- [ ] **Step 3: Commit**

```bash
git add deploy/setup.sh
git commit -m "feat: add server setup script for Ubuntu droplet"
```

---

## Post-Implementation

After all tasks are complete:
1. Run full test suite: `python -m pytest tests/ -v`
2. Test locally: `python run.py --loop --interval=30` (short interval to verify cycle)
3. Push to remote
4. SSH to droplet, run `setup.sh`, configure `.env`, start services
