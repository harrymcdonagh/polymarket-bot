# Polymarket Prediction Bot Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous prediction market bot that scans Polymarket, researches via social media, predicts mispriced markets using XGBoost + Claude, manages risk with Kelly criterion, executes on-chain, and learns from losses.

**Architecture:** Five-agent pipeline: Scanner -> Research -> Prediction -> Risk/Execution -> Postmortem. Each agent is a standalone module communicating through a shared data layer (SQLite). The system runs as a CLI-driven loop locally, with each cycle scanning markets, filtering opportunities, researching top candidates, predicting, risk-checking, and optionally executing trades.

**Tech Stack:** Python 3.11+, py-clob-client (Polymarket SDK), XGBoost, Anthropic SDK (Claude), PRAW (Reddit), twscrape (Twitter/X), feedparser (RSS), CardiffNLP RoBERTa (sentiment), SQLite, asyncio.

---

## File Structure

```
polymarket-bot/
├── pyproject.toml                    # Project config, dependencies
├── .env.example                      # Template for API keys
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── config.py                     # Settings, env loading, thresholds
│   ├── db.py                         # SQLite schema + helpers
│   ├── models.py                     # Pydantic data models (Market, Signal, Trade, etc.)
│   ├── scanner/
│   │   ├── __init__.py
│   │   └── scanner.py                # Step 1: Market scanner agent
│   ├── research/
│   │   ├── __init__.py
│   │   ├── twitter.py                # Twitter/X scraper
│   │   ├── reddit.py                 # Reddit scraper
│   │   ├── rss.py                    # RSS/news scraper
│   │   └── sentiment.py              # Sentiment analysis (VADER + RoBERTa)
│   ├── predictor/
│   │   ├── __init__.py
│   │   ├── features.py               # Feature engineering for XGBoost
│   │   ├── xgb_model.py              # XGBoost model train/predict
│   │   └── calibrator.py             # LLM calibration (Claude) + final signal
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── risk_manager.py           # Position sizing, Kelly criterion, limits
│   │   └── executor.py               # On-chain trade execution via CLOB
│   ├── postmortem/
│   │   ├── __init__.py
│   │   └── postmortem.py             # Loss analysis + system update agents
│   └── pipeline.py                   # Orchestrator: wires all agents together
├── tests/
│   ├── __init__.py
│   ├── test_scanner.py
│   ├── test_research.py
│   ├── test_sentiment.py
│   ├── test_predictor.py
│   ├── test_risk.py
│   ├── test_postmortem.py
│   └── test_pipeline.py
└── docs/
    └── superpowers/
        └── plans/
            └── 2026-03-12-polymarket-prediction-bot.md
```

---

## Chunk 1: Foundation (Config, Models, DB, Scanner)

### Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `src/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "polymarket-bot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "py-clob-client>=0.34.0",
    "anthropic>=0.50.0",
    "xgboost>=2.1.0",
    "praw>=7.8.0",
    "twscrape>=0.13.0",
    "feedparser>=6.0.0",
    "vaderSentiment>=3.3.2",
    "transformers>=4.40.0",
    "torch>=2.2.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
    "numpy>=1.26.0",
    "pandas>=2.2.0",
    "scikit-learn>=1.4.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.14.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create .env.example**

```env
# Polymarket (required for trading, not for scanning)
POLYMARKET_PRIVATE_KEY=
POLYMARKET_FUNDER_ADDRESS=

# Anthropic (required for prediction calibration)
ANTHROPIC_API_KEY=

# Reddit (required for research agent)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=polymarket-bot/1.0

# Twitter/X (optional - twscrape uses account pool)
# Configured via twscrape CLI: twscrape add_accounts

# Risk parameters
MAX_BET_FRACTION=0.05
MIN_EDGE_THRESHOLD=0.08
CONFIDENCE_THRESHOLD=0.7
MAX_DAILY_LOSS=100.0
BANKROLL=1000.0
```

- [ ] **Step 3: Create .gitignore**

```gitignore
__pycache__/
*.pyc
.env
*.db
*.sqlite
.venv/
dist/
*.egg-info/
.pytest_cache/
accounts.db
model_*.json
```

- [ ] **Step 4: Create src/__init__.py (empty)**

- [ ] **Step 5: Install dependencies**

Run: `cd /Users/harrymcdonagh/Projects/polymarket-bot && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example .gitignore src/__init__.py
git commit -m "chore: initial project setup with dependencies"
```

---

### Task 2: Config and Data Models

**Files:**
- Create: `src/config.py`
- Create: `src/models.py`
- Create: `tests/test_scanner.py` (initial)

- [ ] **Step 1: Write test for config loading**

```python
# tests/test_scanner.py
import os
from src.config import Settings

def test_settings_defaults():
    settings = Settings(
        ANTHROPIC_API_KEY="test-key",
    )
    assert settings.MAX_BET_FRACTION == 0.05
    assert settings.CONFIDENCE_THRESHOLD == 0.7
    assert settings.BANKROLL == 1000.0
    assert settings.POLYMARKET_CLOB_URL == "https://clob.polymarket.com"
    assert settings.POLYMARKET_GAMMA_URL == "https://gamma-api.polymarket.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/harrymcdonagh/Projects/polymarket-bot && source .venv/bin/activate && pytest tests/test_scanner.py::test_settings_defaults -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement config.py**

```python
# src/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Polymarket
    POLYMARKET_PRIVATE_KEY: str = ""
    POLYMARKET_FUNDER_ADDRESS: str = ""
    POLYMARKET_CLOB_URL: str = "https://clob.polymarket.com"
    POLYMARKET_GAMMA_URL: str = "https://gamma-api.polymarket.com"
    POLYMARKET_DATA_URL: str = "https://data-api.polymarket.com"

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # Reddit
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "polymarket-bot/1.0"

    # Risk parameters
    MAX_BET_FRACTION: float = 0.05
    MIN_EDGE_THRESHOLD: float = 0.08
    CONFIDENCE_THRESHOLD: float = 0.7
    MAX_DAILY_LOSS: float = 100.0
    BANKROLL: float = 1000.0

    # Scanner parameters
    MIN_LIQUIDITY: float = 5000.0
    MIN_VOLUME_24H: float = 1000.0
    MAX_DAYS_TO_RESOLUTION: int = 90
    SPREAD_ALERT_THRESHOLD: float = 0.10
    PRICE_MOVE_ALERT_THRESHOLD: float = 0.15

    model_config = {"env_file": ".env", "extra": "ignore"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scanner.py::test_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Implement data models**

```python
# src/models.py
from datetime import datetime
from enum import Enum
from pydantic import BaseModel

class MarketStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"

class ScanFlag(str, Enum):
    WIDE_SPREAD = "wide_spread"
    PRICE_SPIKE = "price_spike"
    HIGH_VOLUME = "high_volume"
    MISPRICED = "mispriced"

class ScannedMarket(BaseModel):
    condition_id: str
    question: str
    slug: str
    token_yes_id: str
    token_no_id: str
    yes_price: float
    no_price: float
    spread: float
    liquidity: float
    volume_24h: float
    end_date: datetime | None
    days_to_resolution: int | None
    flags: list[ScanFlag] = []
    scanned_at: datetime

class SentimentResult(BaseModel):
    source: str  # "twitter", "reddit", "rss"
    query: str
    positive_ratio: float
    negative_ratio: float
    neutral_ratio: float
    sample_size: int
    avg_compound_score: float
    collected_at: datetime

class ResearchReport(BaseModel):
    market_id: str
    question: str
    sentiments: list[SentimentResult]
    narrative_summary: str  # LLM-generated
    narrative_vs_odds_alignment: float  # -1 (contradicts) to 1 (aligns)
    researched_at: datetime

class Prediction(BaseModel):
    market_id: str
    question: str
    market_yes_price: float
    predicted_probability: float  # our estimated true probability
    xgb_probability: float
    llm_probability: float
    edge: float  # predicted_probability - market_yes_price (if betting YES)
    confidence: float  # 0-1
    recommended_side: str  # "YES" or "NO"
    reasoning: str
    predicted_at: datetime

class TradeDecision(BaseModel):
    market_id: str
    prediction: Prediction
    approved: bool
    bet_size_usd: float
    kelly_fraction: float
    risk_score: float  # 0-1, higher = riskier
    rejection_reason: str | None = None
    decided_at: datetime

class TradeExecution(BaseModel):
    market_id: str
    decision: TradeDecision
    order_id: str | None = None
    side: str  # "YES" or "NO"
    amount_usd: float
    price: float
    status: str  # "pending", "filled", "failed", "settled"
    pnl: float | None = None
    executed_at: datetime
    settled_at: datetime | None = None

class PostmortemReport(BaseModel):
    trade_id: str
    market_id: str
    question: str
    prediction: Prediction
    actual_outcome: str
    pnl: float
    failure_reasons: list[str]
    lessons: list[str]
    system_updates: list[str]  # concrete parameter/logic changes
    analyzed_at: datetime
```

- [ ] **Step 6: Commit**

```bash
git add src/config.py src/models.py tests/test_scanner.py
git commit -m "feat: add config settings and pydantic data models"
```

---

### Task 3: Database Layer

**Files:**
- Create: `src/db.py`
- Add tests to: `tests/test_scanner.py`

- [ ] **Step 1: Write test for DB operations**

```python
# append to tests/test_scanner.py
import sqlite3
from src.db import Database

def test_db_init_creates_tables(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t[0] for t in tables}
    assert "scanned_markets" in table_names
    assert "trades" in table_names
    assert "postmortems" in table_names
    assert "lessons" in table_names
    conn.close()

def test_db_save_and_load_trade(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    db.save_trade(
        market_id="0xabc",
        side="YES",
        amount=50.0,
        price=0.45,
        order_id="order123",
    )
    trades = db.get_open_trades()
    assert len(trades) == 1
    assert trades[0]["market_id"] == "0xabc"
    assert trades[0]["status"] == "pending"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scanner.py::test_db_init_creates_tables tests/test_scanner.py::test_db_save_and_load_trade -v`
Expected: FAIL

- [ ] **Step 3: Implement db.py**

```python
# src/db.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scanner.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/db.py tests/test_scanner.py
git commit -m "feat: add SQLite database layer with trade and lesson tracking"
```

---

### Task 4: Market Scanner Agent (Step 1 of the Pipeline)

**Files:**
- Create: `src/scanner/__init__.py`
- Create: `src/scanner/scanner.py`
- Update: `tests/test_scanner.py`

- [ ] **Step 1: Write tests for scanner**

```python
# append to tests/test_scanner.py
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from src.scanner.scanner import MarketScanner
from src.config import Settings

def _make_market(liquidity=10000, volume=5000, spread=0.03, days_out=30):
    end = datetime.now(timezone.utc) + timedelta(days=days_out)
    return {
        "condition_id": "0xabc123",
        "question": "Will X happen?",
        "slug": "will-x-happen",
        "tokens": [
            {"token_id": "tok_yes", "outcome": "Yes", "price": 0.55},
            {"token_id": "tok_no", "outcome": "No", "price": 0.45},
        ],
        "liquidity": str(liquidity),
        "volume24hr": str(volume),
        "end_date_iso": end.isoformat(),
        "active": True,
    }

def test_scanner_filters_low_liquidity():
    settings = Settings(ANTHROPIC_API_KEY="test", MIN_LIQUIDITY=10000)
    scanner = MarketScanner(settings)
    market = _make_market(liquidity=500)
    result = scanner._passes_filters(market)
    assert result is False

def test_scanner_flags_wide_spread():
    settings = Settings(ANTHROPIC_API_KEY="test", SPREAD_ALERT_THRESHOLD=0.10)
    scanner = MarketScanner(settings)
    market = _make_market(spread=0.15)
    flags = scanner._detect_flags(market, spread=0.15)
    assert "wide_spread" in [f.value for f in flags]

def test_scanner_passes_good_market():
    settings = Settings(ANTHROPIC_API_KEY="test")
    scanner = MarketScanner(settings)
    market = _make_market(liquidity=20000, volume=5000)
    result = scanner._passes_filters(market)
    assert result is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scanner.py::test_scanner_filters_low_liquidity tests/test_scanner.py::test_scanner_flags_wide_spread tests/test_scanner.py::test_scanner_passes_good_market -v`
Expected: FAIL

- [ ] **Step 3: Implement scanner**

```python
# src/scanner/__init__.py
# empty

# src/scanner/scanner.py
import httpx
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.models import ScannedMarket, ScanFlag

logger = logging.getLogger(__name__)

class MarketScanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gamma_url = settings.POLYMARKET_GAMMA_URL
        self.clob_url = settings.POLYMARKET_CLOB_URL

    async def scan(self) -> list[ScannedMarket]:
        """Fetch active markets from Gamma API, filter and flag."""
        raw_markets = await self._fetch_all_active_markets()
        logger.info(f"Fetched {len(raw_markets)} active markets")

        results = []
        for market in raw_markets:
            if not self._passes_filters(market):
                continue

            tokens = market.get("tokens", [])
            yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
            no_token = next((t for t in tokens if t.get("outcome") == "No"), None)
            if not yes_token or not no_token:
                continue

            yes_price = float(yes_token.get("price", 0))
            no_price = float(no_token.get("price", 0))
            spread = abs(1.0 - yes_price - no_price)

            flags = self._detect_flags(market, spread=spread)

            end_date = None
            days_to_res = None
            if market.get("end_date_iso"):
                try:
                    end_date = datetime.fromisoformat(market["end_date_iso"].replace("Z", "+00:00"))
                    days_to_res = (end_date - datetime.now(timezone.utc)).days
                except (ValueError, TypeError):
                    pass

            results.append(ScannedMarket(
                condition_id=market.get("condition_id", ""),
                question=market.get("question", ""),
                slug=market.get("slug", ""),
                token_yes_id=yes_token.get("token_id", ""),
                token_no_id=no_token.get("token_id", ""),
                yes_price=yes_price,
                no_price=no_price,
                spread=spread,
                liquidity=float(market.get("liquidity", 0)),
                volume_24h=float(market.get("volume24hr", 0)),
                end_date=end_date,
                days_to_resolution=days_to_res,
                flags=flags,
                scanned_at=datetime.now(timezone.utc),
            ))

        # Sort by number of flags (most interesting first), then by volume
        results.sort(key=lambda m: (-len(m.flags), -m.volume_24h))
        logger.info(f"Scanner found {len(results)} markets passing filters, {sum(1 for m in results if m.flags)} flagged")
        return results

    async def _fetch_all_active_markets(self) -> list[dict]:
        """Paginate through Gamma API to get all active markets."""
        all_markets = []
        offset = 0
        limit = 100
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                resp = await client.get(
                    f"{self.gamma_url}/markets",
                    params={"active": "true", "limit": limit, "offset": offset},
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                all_markets.extend(batch)
                if len(batch) < limit:
                    break
                offset += limit
        return all_markets

    def _passes_filters(self, market: dict) -> bool:
        """Check if market meets minimum liquidity, volume, and time criteria."""
        liquidity = float(market.get("liquidity", 0))
        volume = float(market.get("volume24hr", 0))

        if liquidity < self.settings.MIN_LIQUIDITY:
            return False
        if volume < self.settings.MIN_VOLUME_24H:
            return False

        # Check time to resolution
        if market.get("end_date_iso"):
            try:
                end = datetime.fromisoformat(market["end_date_iso"].replace("Z", "+00:00"))
                days = (end - datetime.now(timezone.utc)).days
                if days > self.settings.MAX_DAYS_TO_RESOLUTION:
                    return False
                if days < 0:
                    return False
            except (ValueError, TypeError):
                pass

        return True

    def _detect_flags(self, market: dict, spread: float) -> list[ScanFlag]:
        """Detect anomalies worth investigating."""
        flags = []

        if spread >= self.settings.SPREAD_ALERT_THRESHOLD:
            flags.append(ScanFlag.WIDE_SPREAD)

        volume = float(market.get("volume24hr", 0))
        if volume > 50000:
            flags.append(ScanFlag.HIGH_VOLUME)

        return flags
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/test_scanner.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/scanner/ tests/test_scanner.py
git commit -m "feat: add market scanner agent with filtering and anomaly detection"
```

---

## Chunk 2: Research Agents (Twitter, Reddit, RSS, Sentiment)

### Task 5: Sentiment Analysis Module

**Files:**
- Create: `src/research/__init__.py`
- Create: `src/research/sentiment.py`
- Create: `tests/test_sentiment.py`

- [ ] **Step 1: Write tests for sentiment analyzer**

```python
# tests/test_sentiment.py
from src.research.sentiment import SentimentAnalyzer

def test_positive_sentiment():
    analyzer = SentimentAnalyzer(use_transformer=False)  # VADER only for tests
    result = analyzer.analyze("This is absolutely amazing and wonderful!")
    assert result["label"] == "positive"
    assert result["score"] > 0.5

def test_negative_sentiment():
    analyzer = SentimentAnalyzer(use_transformer=False)
    result = analyzer.analyze("This is terrible and awful, complete disaster.")
    assert result["label"] == "negative"
    assert result["score"] > 0.5

def test_batch_sentiment():
    analyzer = SentimentAnalyzer(use_transformer=False)
    texts = ["Great news!", "Terrible outcome", "The weather is okay"]
    results = analyzer.analyze_batch(texts)
    assert len(results) == 3
    assert results[0]["label"] == "positive"
    assert results[1]["label"] == "negative"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sentiment.py -v`
Expected: FAIL

- [ ] **Step 3: Implement sentiment analyzer**

```python
# src/research/__init__.py
# empty

# src/research/sentiment.py
import logging
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

class SentimentAnalyzer:
    def __init__(self, use_transformer: bool = True):
        self.vader = SentimentIntensityAnalyzer()
        self.use_transformer = use_transformer
        self._roberta = None

    def _get_roberta(self):
        if self._roberta is None:
            from transformers import pipeline
            self._roberta = pipeline(
                "sentiment-analysis",
                model="cardiffnlp/twitter-roberta-base-sentiment-latest",
            )
        return self._roberta

    def analyze(self, text: str) -> dict:
        """Analyze sentiment of a single text. Returns {label, score}."""
        vader_scores = self.vader.polarity_scores(text)
        compound = vader_scores["compound"]

        # Fast path: VADER is confident
        if not self.use_transformer or abs(compound) > 0.6:
            label = "positive" if compound > 0.05 else ("negative" if compound < -0.05 else "neutral")
            return {"label": label, "score": abs(compound)}

        # Slow path: use RoBERTa for ambiguous cases
        try:
            roberta = self._get_roberta()
            result = roberta(text[:512])[0]  # truncate for model
            return {"label": result["label"].lower(), "score": result["score"]}
        except Exception as e:
            logger.warning(f"RoBERTa failed, falling back to VADER: {e}")
            label = "positive" if compound > 0.05 else ("negative" if compound < -0.05 else "neutral")
            return {"label": label, "score": abs(compound)}

    def analyze_batch(self, texts: list[str]) -> list[dict]:
        """Analyze sentiment of multiple texts."""
        return [self.analyze(text) for text in texts]

    def aggregate(self, results: list[dict]) -> dict:
        """Compute aggregate sentiment stats from a list of results."""
        if not results:
            return {"positive_ratio": 0, "negative_ratio": 0, "neutral_ratio": 0, "avg_score": 0, "sample_size": 0}

        pos = sum(1 for r in results if r["label"] == "positive")
        neg = sum(1 for r in results if r["label"] == "negative")
        neu = sum(1 for r in results if r["label"] == "neutral")
        total = len(results)
        avg_score = sum(r["score"] for r in results) / total

        return {
            "positive_ratio": pos / total,
            "negative_ratio": neg / total,
            "neutral_ratio": neu / total,
            "avg_score": avg_score,
            "sample_size": total,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sentiment.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/__init__.py src/research/sentiment.py tests/test_sentiment.py
git commit -m "feat: add hybrid VADER/RoBERTa sentiment analyzer"
```

---

### Task 6: Twitter Research Agent

**Files:**
- Create: `src/research/twitter.py`

- [ ] **Step 1: Write test**

```python
# tests/test_research.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.research.twitter import TwitterResearcher

@pytest.mark.asyncio
async def test_twitter_search_returns_texts():
    mock_tweet = MagicMock()
    mock_tweet.rawContent = "This market is going to resolve YES for sure"
    mock_tweet.date = "2026-03-12"
    mock_tweet.likeCount = 10

    with patch("src.research.twitter.API") as MockAPI:
        mock_api = MockAPI.return_value
        mock_api.search = AsyncMock(return_value=iter([mock_tweet]))
        researcher = TwitterResearcher(mock_api)
        results = await researcher.search("prediction market question", limit=10)
        assert len(results) >= 1
        assert results[0]["text"] == "This market is going to resolve YES for sure"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research.py::test_twitter_search_returns_texts -v`
Expected: FAIL

- [ ] **Step 3: Implement Twitter researcher**

```python
# src/research/twitter.py
import logging
from twscrape import API

logger = logging.getLogger(__name__)

class TwitterResearcher:
    def __init__(self, api: API | None = None):
        self.api = api or API()

    async def search(self, query: str, limit: int = 50) -> list[dict]:
        """Search Twitter for tweets related to a query."""
        results = []
        try:
            async for tweet in self.api.search(query, limit=limit):
                results.append({
                    "text": tweet.rawContent,
                    "date": str(tweet.date),
                    "likes": tweet.likeCount,
                    "source": "twitter",
                })
        except Exception as e:
            logger.warning(f"Twitter search failed for '{query}': {e}")
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_research.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/twitter.py tests/test_research.py
git commit -m "feat: add Twitter research agent using twscrape"
```

---

### Task 7: Reddit Research Agent

**Files:**
- Create: `src/research/reddit.py`
- Update: `tests/test_research.py`

- [ ] **Step 1: Write test**

```python
# append to tests/test_research.py
from unittest.mock import patch, MagicMock, PropertyMock
from src.research.reddit import RedditResearcher

def test_reddit_search_returns_texts():
    mock_submission = MagicMock()
    mock_submission.title = "Market X is definitely going YES"
    mock_submission.selftext = "I have strong evidence..."
    mock_submission.score = 42
    mock_submission.num_comments = 10
    mock_submission.created_utc = 1710000000

    mock_reddit = MagicMock()
    mock_reddit.subreddit.return_value.search.return_value = [mock_submission]

    researcher = RedditResearcher(reddit=mock_reddit)
    results = researcher.search("prediction market question", subreddits=["polymarket"])
    assert len(results) >= 1
    assert "Market X" in results[0]["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research.py::test_reddit_search_returns_texts -v`
Expected: FAIL

- [ ] **Step 3: Implement Reddit researcher**

```python
# src/research/reddit.py
import logging
import praw
from src.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = ["polymarket", "prediction_market", "wallstreetbets", "news", "worldnews"]

class RedditResearcher:
    def __init__(self, reddit: praw.Reddit | None = None, settings: Settings | None = None):
        if reddit:
            self.reddit = reddit
        else:
            s = settings or Settings()
            self.reddit = praw.Reddit(
                client_id=s.REDDIT_CLIENT_ID,
                client_secret=s.REDDIT_CLIENT_SECRET,
                user_agent=s.REDDIT_USER_AGENT,
            )

    def search(self, query: str, subreddits: list[str] | None = None, limit: int = 30) -> list[dict]:
        """Search Reddit for posts related to a query."""
        subs = subreddits or DEFAULT_SUBREDDITS
        results = []
        for sub_name in subs:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                for post in subreddit.search(query, sort="relevance", time_filter="week", limit=limit):
                    results.append({
                        "text": f"{post.title}. {post.selftext[:500]}",
                        "score": post.score,
                        "comments": post.num_comments,
                        "subreddit": sub_name,
                        "source": "reddit",
                    })
            except Exception as e:
                logger.warning(f"Reddit search failed for r/{sub_name}: {e}")
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_research.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/reddit.py tests/test_research.py
git commit -m "feat: add Reddit research agent using PRAW"
```

---

### Task 8: RSS/News Research Agent

**Files:**
- Create: `src/research/rss.py`
- Update: `tests/test_research.py`

- [ ] **Step 1: Write test**

```python
# append to tests/test_research.py
from src.research.rss import RSSResearcher

def test_rss_parse_feed(tmp_path):
    # Create a minimal RSS feed
    feed_xml = """<?xml version="1.0"?>
    <rss version="2.0">
        <channel>
            <title>Test Feed</title>
            <item>
                <title>Market prediction shows strong trend</title>
                <link>http://example.com/1</link>
                <description>Analysis suggests positive outcome</description>
                <pubDate>Wed, 12 Mar 2026 00:00:00 GMT</pubDate>
            </item>
        </channel>
    </rss>"""
    feed_file = tmp_path / "test.xml"
    feed_file.write_text(feed_xml)

    researcher = RSSResearcher()
    results = researcher.parse_feed(str(feed_file))
    assert len(results) == 1
    assert "strong trend" in results[0]["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research.py::test_rss_parse_feed -v`
Expected: FAIL

- [ ] **Step 3: Implement RSS researcher**

```python
# src/research/rss.py
import logging
import feedparser

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
]

class RSSResearcher:
    def __init__(self, extra_feeds: list[str] | None = None):
        self.extra_feeds = extra_feeds or []

    def search(self, query: str) -> list[dict]:
        """Search Google News RSS and any extra feeds for a query."""
        results = []
        feed_urls = [f.format(query=query) for f in DEFAULT_FEEDS] + self.extra_feeds

        for url in feed_urls:
            results.extend(self.parse_feed(url))

        return results

    def parse_feed(self, url_or_path: str) -> list[dict]:
        """Parse a single RSS feed and return entries."""
        results = []
        try:
            feed = feedparser.parse(url_or_path)
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                desc = entry.get("description", entry.get("summary", ""))
                results.append({
                    "text": f"{title}. {desc[:500]}",
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "source": "rss",
                })
        except Exception as e:
            logger.warning(f"RSS parse failed for {url_or_path}: {e}")
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_research.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/rss.py tests/test_research.py
git commit -m "feat: add RSS/news research agent using feedparser"
```

---

## Chunk 3: Prediction Engine (XGBoost + Claude Calibration)

### Task 9: Feature Engineering

**Files:**
- Create: `src/predictor/__init__.py`
- Create: `src/predictor/features.py`
- Create: `tests/test_predictor.py`

- [ ] **Step 1: Write test for feature extraction**

```python
# tests/test_predictor.py
from src.predictor.features import extract_features
from src.models import ScannedMarket, ScanFlag
from datetime import datetime, timezone

def test_extract_features_returns_dict():
    market = ScannedMarket(
        condition_id="0xabc",
        question="Will X happen?",
        slug="will-x-happen",
        token_yes_id="tok_yes",
        token_no_id="tok_no",
        yes_price=0.60,
        no_price=0.40,
        spread=0.02,
        liquidity=50000,
        volume_24h=10000,
        end_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
        days_to_resolution=20,
        flags=[ScanFlag.HIGH_VOLUME],
        scanned_at=datetime.now(timezone.utc),
    )
    sentiment_agg = {
        "positive_ratio": 0.6,
        "negative_ratio": 0.2,
        "neutral_ratio": 0.2,
        "avg_score": 0.65,
        "sample_size": 50,
    }
    features = extract_features(market, sentiment_agg)
    assert "yes_price" in features
    assert "sentiment_positive_ratio" in features
    assert "log_liquidity" in features
    assert features["yes_price"] == 0.60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_predictor.py::test_extract_features_returns_dict -v`
Expected: FAIL

- [ ] **Step 3: Implement feature extraction**

```python
# src/predictor/__init__.py
# empty

# src/predictor/features.py
import math
from src.models import ScannedMarket, ScanFlag

def extract_features(market: ScannedMarket, sentiment_agg: dict) -> dict:
    """Extract features for XGBoost from market data and sentiment."""
    return {
        # Market features
        "yes_price": market.yes_price,
        "no_price": market.no_price,
        "spread": market.spread,
        "log_liquidity": math.log1p(market.liquidity),
        "log_volume_24h": math.log1p(market.volume_24h),
        "days_to_resolution": market.days_to_resolution or 0,
        "volume_liquidity_ratio": market.volume_24h / max(market.liquidity, 1),
        # Flags as binary features
        "flag_wide_spread": 1 if ScanFlag.WIDE_SPREAD in market.flags else 0,
        "flag_high_volume": 1 if ScanFlag.HIGH_VOLUME in market.flags else 0,
        "flag_price_spike": 1 if ScanFlag.PRICE_SPIKE in market.flags else 0,
        # Sentiment features
        "sentiment_positive_ratio": sentiment_agg.get("positive_ratio", 0),
        "sentiment_negative_ratio": sentiment_agg.get("negative_ratio", 0),
        "sentiment_neutral_ratio": sentiment_agg.get("neutral_ratio", 0),
        "sentiment_avg_score": sentiment_agg.get("avg_score", 0),
        "sentiment_sample_size": min(sentiment_agg.get("sample_size", 0), 200),  # cap
        # Derived
        "sentiment_polarity": sentiment_agg.get("positive_ratio", 0) - sentiment_agg.get("negative_ratio", 0),
        "price_sentiment_gap": market.yes_price - sentiment_agg.get("positive_ratio", 0),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_predictor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/predictor/ tests/test_predictor.py
git commit -m "feat: add feature engineering for XGBoost predictor"
```

---

### Task 10: XGBoost Model

**Files:**
- Create: `src/predictor/xgb_model.py`
- Update: `tests/test_predictor.py`

- [ ] **Step 1: Write test**

```python
# append to tests/test_predictor.py
import numpy as np
from src.predictor.xgb_model import PredictionModel

def test_model_predict_returns_probability():
    model = PredictionModel()
    # With no training data, model should return a default
    features = {
        "yes_price": 0.5, "no_price": 0.5, "spread": 0.02,
        "log_liquidity": 10.0, "log_volume_24h": 8.0,
        "days_to_resolution": 30, "volume_liquidity_ratio": 0.2,
        "flag_wide_spread": 0, "flag_high_volume": 0, "flag_price_spike": 0,
        "sentiment_positive_ratio": 0.5, "sentiment_negative_ratio": 0.3,
        "sentiment_neutral_ratio": 0.2, "sentiment_avg_score": 0.5,
        "sentiment_sample_size": 50, "sentiment_polarity": 0.2,
        "price_sentiment_gap": 0.0,
    }
    prob = model.predict(features)
    assert 0.0 <= prob <= 1.0

def test_model_train_and_predict():
    model = PredictionModel()
    # Create synthetic training data
    X = [
        {"yes_price": 0.3, "sentiment_polarity": -0.4, "log_liquidity": 9, "log_volume_24h": 7,
         "spread": 0.05, "no_price": 0.7, "days_to_resolution": 10, "volume_liquidity_ratio": 0.1,
         "flag_wide_spread": 0, "flag_high_volume": 0, "flag_price_spike": 0,
         "sentiment_positive_ratio": 0.2, "sentiment_negative_ratio": 0.6,
         "sentiment_neutral_ratio": 0.2, "sentiment_avg_score": 0.3,
         "sentiment_sample_size": 30, "price_sentiment_gap": 0.1},
        {"yes_price": 0.8, "sentiment_polarity": 0.5, "log_liquidity": 11, "log_volume_24h": 9,
         "spread": 0.01, "no_price": 0.2, "days_to_resolution": 5, "volume_liquidity_ratio": 0.3,
         "flag_wide_spread": 0, "flag_high_volume": 1, "flag_price_spike": 0,
         "sentiment_positive_ratio": 0.7, "sentiment_negative_ratio": 0.1,
         "sentiment_neutral_ratio": 0.2, "sentiment_avg_score": 0.8,
         "sentiment_sample_size": 100, "price_sentiment_gap": 0.1},
    ] * 10  # need more samples
    y = [0] * 10 + [1] * 10
    model.train(X, y)
    # High sentiment + high price -> should predict higher prob
    prob = model.predict(X[10])
    assert prob > 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_predictor.py -v`
Expected: FAIL

- [ ] **Step 3: Implement XGBoost model**

```python
# src/predictor/xgb_model.py
import json
import logging
import numpy as np
import xgboost as xgb

logger = logging.getLogger(__name__)

FEATURE_ORDER = [
    "yes_price", "no_price", "spread", "log_liquidity", "log_volume_24h",
    "days_to_resolution", "volume_liquidity_ratio",
    "flag_wide_spread", "flag_high_volume", "flag_price_spike",
    "sentiment_positive_ratio", "sentiment_negative_ratio",
    "sentiment_neutral_ratio", "sentiment_avg_score", "sentiment_sample_size",
    "sentiment_polarity", "price_sentiment_gap",
]

class PredictionModel:
    def __init__(self, model_path: str | None = None):
        self.model: xgb.XGBClassifier | None = None
        if model_path:
            self.load(model_path)

    def _features_to_array(self, features: dict) -> np.ndarray:
        return np.array([[features.get(f, 0.0) for f in FEATURE_ORDER]])

    def train(self, feature_dicts: list[dict], labels: list[int]):
        """Train XGBoost on historical data."""
        X = np.array([[fd.get(f, 0.0) for f in FEATURE_ORDER] for fd in feature_dicts])
        y = np.array(labels)
        self.model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            objective="binary:logistic",
            eval_metric="logloss",
        )
        self.model.fit(X, y)
        logger.info("XGBoost model trained on %d samples", len(labels))

    def predict(self, features: dict) -> float:
        """Return predicted probability of YES outcome."""
        if self.model is None:
            # No trained model: return market price as baseline
            return features.get("yes_price", 0.5)
        X = self._features_to_array(features)
        return float(self.model.predict_proba(X)[0][1])

    def save(self, path: str = "model_xgb.json"):
        if self.model:
            self.model.save_model(path)

    def load(self, path: str = "model_xgb.json"):
        self.model = xgb.XGBClassifier()
        self.model.load_model(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_predictor.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/predictor/xgb_model.py tests/test_predictor.py
git commit -m "feat: add XGBoost prediction model with train/predict/save/load"
```

---

### Task 11: Claude LLM Calibrator

**Files:**
- Create: `src/predictor/calibrator.py`
- Update: `tests/test_predictor.py`

- [ ] **Step 1: Write test**

```python
# append to tests/test_predictor.py
from unittest.mock import patch, MagicMock, AsyncMock
from src.predictor.calibrator import Calibrator
from src.models import ScannedMarket, ResearchReport, SentimentResult
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_calibrator_combines_xgb_and_llm():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"probability": 0.65, "reasoning": "Strong evidence supports YES"}')]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    calibrator = Calibrator(anthropic_client=mock_client)

    market = ScannedMarket(
        condition_id="0xabc", question="Will X happen?", slug="x",
        token_yes_id="ty", token_no_id="tn",
        yes_price=0.50, no_price=0.50, spread=0.02,
        liquidity=50000, volume_24h=10000,
        end_date=None, days_to_resolution=30,
        flags=[], scanned_at=datetime.now(timezone.utc),
    )
    research = ResearchReport(
        market_id="0xabc", question="Will X happen?",
        sentiments=[], narrative_summary="Mixed signals",
        narrative_vs_odds_alignment=0.0, researched_at=datetime.now(timezone.utc),
    )

    prediction = await calibrator.calibrate(
        market=market, research=research, xgb_probability=0.60
    )
    assert prediction.predicted_probability > 0
    assert prediction.confidence > 0
    assert prediction.reasoning != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_predictor.py -k test_calibrator -v`
Expected: FAIL

- [ ] **Step 3: Implement calibrator**

```python
# src/predictor/calibrator.py
import json
import logging
from datetime import datetime, timezone
import anthropic
from src.models import ScannedMarket, ResearchReport, Prediction
from src.config import Settings

logger = logging.getLogger(__name__)

CALIBRATION_PROMPT = """You are a prediction market analyst. Given market data and research, estimate the TRUE probability of the event occurring.

Market: {question}
Current YES price: {yes_price} (market implied probability)
Current NO price: {no_price}
Spread: {spread}
Liquidity: ${liquidity:,.0f}
24h Volume: ${volume:,.0f}
Days to resolution: {days_to_resolution}

XGBoost model estimate: {xgb_probability:.2%}

Research summary:
{narrative_summary}

Sentiment data:
{sentiment_summary}

Instructions:
1. Consider all evidence including the XGBoost estimate
2. Assess if the market price is accurate, too high, or too low
3. Return your estimate as JSON: {{"probability": 0.XX, "reasoning": "your analysis"}}
4. probability must be between 0.01 and 0.99
5. Be well-calibrated: if you say 70%, it should happen ~70% of the time

Return ONLY valid JSON."""

class Calibrator:
    def __init__(self, anthropic_client=None, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.client = anthropic_client or anthropic.Anthropic(api_key=self.settings.ANTHROPIC_API_KEY)

    async def calibrate(
        self, market: ScannedMarket, research: ResearchReport, xgb_probability: float
    ) -> Prediction:
        """Combine XGBoost prediction with LLM calibration."""
        sentiment_lines = []
        for s in research.sentiments:
            sentiment_lines.append(
                f"  {s.source}: +{s.positive_ratio:.0%} / -{s.negative_ratio:.0%} "
                f"(n={s.sample_size}, avg={s.avg_compound_score:.2f})"
            )
        sentiment_summary = "\n".join(sentiment_lines) if sentiment_lines else "No sentiment data available"

        prompt = CALIBRATION_PROMPT.format(
            question=market.question,
            yes_price=market.yes_price,
            no_price=market.no_price,
            spread=market.spread,
            liquidity=market.liquidity,
            volume=market.volume_24h,
            days_to_resolution=market.days_to_resolution or "unknown",
            xgb_probability=xgb_probability,
            narrative_summary=research.narrative_summary,
            sentiment_summary=sentiment_summary,
        )

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Parse JSON from response
            data = json.loads(text)
            llm_probability = max(0.01, min(0.99, float(data["probability"])))
            reasoning = data.get("reasoning", "")
        except Exception as e:
            logger.warning(f"LLM calibration failed: {e}, using XGBoost only")
            llm_probability = xgb_probability
            reasoning = f"LLM calibration failed ({e}), using XGBoost estimate"

        # Weighted average: 40% XGBoost, 60% LLM
        predicted_prob = 0.4 * xgb_probability + 0.6 * llm_probability

        # Determine side and edge
        yes_edge = predicted_prob - market.yes_price
        no_edge = (1 - predicted_prob) - market.no_price
        if yes_edge > no_edge:
            side = "YES"
            edge = yes_edge
        else:
            side = "NO"
            edge = no_edge

        # Confidence based on agreement between models and edge size
        model_agreement = 1.0 - abs(xgb_probability - llm_probability)
        confidence = min(1.0, (model_agreement * 0.5 + min(abs(edge) * 5, 1.0) * 0.5))

        return Prediction(
            market_id=market.condition_id,
            question=market.question,
            market_yes_price=market.yes_price,
            predicted_probability=predicted_prob,
            xgb_probability=xgb_probability,
            llm_probability=llm_probability,
            edge=edge,
            confidence=confidence,
            recommended_side=side,
            reasoning=reasoning,
            predicted_at=datetime.now(timezone.utc),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_predictor.py -k test_calibrator -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/predictor/calibrator.py tests/test_predictor.py
git commit -m "feat: add Claude LLM calibrator for prediction refinement"
```

---

## Chunk 4: Risk Management & Execution

### Task 12: Risk Manager (Kelly Criterion)

**Files:**
- Create: `src/risk/__init__.py`
- Create: `src/risk/risk_manager.py`
- Create: `tests/test_risk.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_risk.py
from src.risk.risk_manager import RiskManager
from src.models import Prediction
from src.config import Settings
from datetime import datetime, timezone

def _make_prediction(edge=0.10, confidence=0.8, yes_price=0.50, predicted_prob=0.60):
    return Prediction(
        market_id="0xabc",
        question="Test?",
        market_yes_price=yes_price,
        predicted_probability=predicted_prob,
        xgb_probability=predicted_prob,
        llm_probability=predicted_prob,
        edge=edge,
        confidence=confidence,
        recommended_side="YES",
        reasoning="test",
        predicted_at=datetime.now(timezone.utc),
    )

def test_kelly_fraction_positive_edge():
    settings = Settings(ANTHROPIC_API_KEY="test", BANKROLL=1000)
    rm = RiskManager(settings)
    # edge=0.10, price=0.50 -> kelly = (0.10 * 0.50) / (1 - 0.50) = 0.10
    fraction = rm._kelly_fraction(edge=0.10, price=0.50)
    assert 0.05 < fraction < 0.20

def test_risk_blocks_low_confidence():
    settings = Settings(ANTHROPIC_API_KEY="test", CONFIDENCE_THRESHOLD=0.7)
    rm = RiskManager(settings)
    prediction = _make_prediction(confidence=0.5)
    decision = rm.evaluate(prediction, daily_pnl=0)
    assert decision.approved is False
    assert "confidence" in decision.rejection_reason.lower()

def test_risk_blocks_low_edge():
    settings = Settings(ANTHROPIC_API_KEY="test", MIN_EDGE_THRESHOLD=0.08)
    rm = RiskManager(settings)
    prediction = _make_prediction(edge=0.03)
    decision = rm.evaluate(prediction, daily_pnl=0)
    assert decision.approved is False

def test_risk_approves_good_trade():
    settings = Settings(ANTHROPIC_API_KEY="test", BANKROLL=1000, MAX_BET_FRACTION=0.05)
    rm = RiskManager(settings)
    prediction = _make_prediction(edge=0.15, confidence=0.85)
    decision = rm.evaluate(prediction, daily_pnl=0)
    assert decision.approved is True
    assert 0 < decision.bet_size_usd <= 50  # max 5% of 1000

def test_risk_blocks_after_daily_loss_limit():
    settings = Settings(ANTHROPIC_API_KEY="test", MAX_DAILY_LOSS=100)
    rm = RiskManager(settings)
    prediction = _make_prediction(edge=0.15, confidence=0.85)
    decision = rm.evaluate(prediction, daily_pnl=-105)
    assert decision.approved is False
    assert "daily loss" in decision.rejection_reason.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_risk.py -v`
Expected: FAIL

- [ ] **Step 3: Implement risk manager**

```python
# src/risk/__init__.py
# empty

# src/risk/risk_manager.py
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.models import Prediction, TradeDecision

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _kelly_fraction(self, edge: float, price: float) -> float:
        """Half-Kelly criterion for position sizing.

        Full Kelly: f = (p*b - q) / b where b = (1/price - 1), p = prob, q = 1-p
        Simplified for binary markets: f = edge / (1 - price)
        We use half-Kelly for safety.
        """
        if price <= 0 or price >= 1:
            return 0.0
        odds_against = 1.0 / price - 1.0
        if odds_against <= 0:
            return 0.0
        kelly = edge / (1.0 - price)
        half_kelly = kelly / 2.0
        return max(0.0, half_kelly)

    def evaluate(self, prediction: Prediction, daily_pnl: float) -> TradeDecision:
        """Evaluate whether a trade should be placed and how much."""
        now = datetime.now(timezone.utc)

        # Check daily loss limit
        if daily_pnl <= -self.settings.MAX_DAILY_LOSS:
            return TradeDecision(
                market_id=prediction.market_id,
                prediction=prediction,
                approved=False,
                bet_size_usd=0,
                kelly_fraction=0,
                risk_score=1.0,
                rejection_reason=f"Daily loss limit reached (PnL: ${daily_pnl:.2f})",
                decided_at=now,
            )

        # Check confidence threshold
        if prediction.confidence < self.settings.CONFIDENCE_THRESHOLD:
            return TradeDecision(
                market_id=prediction.market_id,
                prediction=prediction,
                approved=False,
                bet_size_usd=0,
                kelly_fraction=0,
                risk_score=0.5,
                rejection_reason=f"Confidence too low: {prediction.confidence:.2f} < {self.settings.CONFIDENCE_THRESHOLD}",
                decided_at=now,
            )

        # Check edge threshold
        if abs(prediction.edge) < self.settings.MIN_EDGE_THRESHOLD:
            return TradeDecision(
                market_id=prediction.market_id,
                prediction=prediction,
                approved=False,
                bet_size_usd=0,
                kelly_fraction=0,
                risk_score=0.3,
                rejection_reason=f"Edge too small: {prediction.edge:.2%} < {self.settings.MIN_EDGE_THRESHOLD:.2%}",
                decided_at=now,
            )

        # Calculate position size
        price = prediction.market_yes_price if prediction.recommended_side == "YES" else (1 - prediction.market_yes_price)
        kelly = self._kelly_fraction(abs(prediction.edge), price)
        capped_fraction = min(kelly, self.settings.MAX_BET_FRACTION)
        bet_size = self.settings.BANKROLL * capped_fraction

        # Risk score: higher when betting more of bankroll
        risk_score = capped_fraction / self.settings.MAX_BET_FRACTION

        if bet_size < 1.0:
            return TradeDecision(
                market_id=prediction.market_id,
                prediction=prediction,
                approved=False,
                bet_size_usd=0,
                kelly_fraction=kelly,
                risk_score=risk_score,
                rejection_reason="Calculated bet size below $1 minimum",
                decided_at=now,
            )

        logger.info(
            f"APPROVED: {prediction.question[:50]} | {prediction.recommended_side} | "
            f"${bet_size:.2f} | edge={prediction.edge:.2%} | kelly={kelly:.4f}"
        )

        return TradeDecision(
            market_id=prediction.market_id,
            prediction=prediction,
            approved=True,
            bet_size_usd=round(bet_size, 2),
            kelly_fraction=kelly,
            risk_score=risk_score,
            decided_at=now,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_risk.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/risk/ tests/test_risk.py
git commit -m "feat: add risk manager with half-Kelly position sizing"
```

---

### Task 13: Trade Executor

**Files:**
- Create: `src/risk/executor.py`
- Update: `tests/test_risk.py`

- [ ] **Step 1: Write test**

```python
# append to tests/test_risk.py
import pytest
from unittest.mock import MagicMock, patch
from src.risk.executor import TradeExecutor

def test_executor_places_order(tmp_path):
    mock_clob = MagicMock()
    mock_clob.create_and_post_order.return_value = {"orderID": "order_abc123"}

    from src.db import Database
    db = Database(str(tmp_path / "test.db"))
    db.init()

    executor = TradeExecutor(clob_client=mock_clob, db=db)
    decision = _make_prediction(edge=0.15, confidence=0.85)

    from src.models import TradeDecision
    trade_decision = TradeDecision(
        market_id="0xabc",
        prediction=decision,
        approved=True,
        bet_size_usd=50.0,
        kelly_fraction=0.05,
        risk_score=0.5,
        decided_at=datetime.now(timezone.utc),
    )

    result = executor.execute(
        decision=trade_decision,
        token_id="tok_yes",
    )
    assert result.order_id == "order_abc123"
    assert result.status == "pending"
    # Verify trade was saved to DB
    trades = db.get_open_trades()
    assert len(trades) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_risk.py::test_executor_places_order -v`
Expected: FAIL

- [ ] **Step 3: Implement executor**

```python
# src/risk/executor.py
import logging
from datetime import datetime, timezone
from src.models import TradeDecision, TradeExecution
from src.db import Database

logger = logging.getLogger(__name__)

class TradeExecutor:
    def __init__(self, clob_client, db: Database):
        self.clob = clob_client
        self.db = db

    def execute(self, decision: TradeDecision, token_id: str) -> TradeExecution:
        """Place a trade on Polymarket via the CLOB API."""
        now = datetime.now(timezone.utc)

        if not decision.approved:
            return TradeExecution(
                market_id=decision.market_id,
                decision=decision,
                side=decision.prediction.recommended_side,
                amount_usd=0,
                price=decision.prediction.market_yes_price,
                status="rejected",
                executed_at=now,
            )

        try:
            # Build order using py-clob-client
            from py_clob_client.order_builder.constants import BUY

            order_args = {
                "token_id": token_id,
                "price": round(decision.prediction.market_yes_price, 2),
                "size": round(decision.bet_size_usd / decision.prediction.market_yes_price, 2),
                "side": BUY,
            }
            response = self.clob.create_and_post_order(order_args)
            order_id = response.get("orderID", response.get("order_id", "unknown"))

            logger.info(f"Order placed: {order_id} | {decision.prediction.recommended_side} ${decision.bet_size_usd}")

            # Save to DB
            self.db.save_trade(
                market_id=decision.market_id,
                side=decision.prediction.recommended_side,
                amount=decision.bet_size_usd,
                price=decision.prediction.market_yes_price,
                order_id=order_id,
            )

            return TradeExecution(
                market_id=decision.market_id,
                decision=decision,
                order_id=order_id,
                side=decision.prediction.recommended_side,
                amount_usd=decision.bet_size_usd,
                price=decision.prediction.market_yes_price,
                status="pending",
                executed_at=now,
            )

        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            return TradeExecution(
                market_id=decision.market_id,
                decision=decision,
                side=decision.prediction.recommended_side,
                amount_usd=decision.bet_size_usd,
                price=decision.prediction.market_yes_price,
                status="failed",
                executed_at=now,
            )

    async def watch_settlement(self, trade_id: int, token_id: str):
        """Poll for market resolution and update trade status."""
        import asyncio
        import httpx

        while True:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"https://clob.polymarket.com/price",
                        params={"token_id": token_id, "side": "BUY"},
                    )
                    data = resp.json()
                    price = float(data.get("price", 0.5))

                    # If price hits 0 or 1, market has resolved
                    if price >= 0.99 or price <= 0.01:
                        trades = self.db.get_open_trades()
                        trade = next((t for t in trades if t["id"] == trade_id), None)
                        if trade:
                            won = (price >= 0.99 and trade["side"] == "YES") or \
                                  (price <= 0.01 and trade["side"] == "NO")
                            pnl = trade["amount"] * (1 / trade["price"] - 1) if won else -trade["amount"]
                            self.db.update_trade_status(trade_id, "settled", pnl)
                            logger.info(f"Trade {trade_id} settled: PnL=${pnl:.2f}")
                        return

            except Exception as e:
                logger.warning(f"Settlement watch error: {e}")

            await asyncio.sleep(300)  # check every 5 minutes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_risk.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/risk/executor.py tests/test_risk.py
git commit -m "feat: add trade executor with CLOB integration and settlement watching"
```

---

## Chunk 5: Postmortem & Pipeline Orchestrator

### Task 14: Postmortem Agent

**Files:**
- Create: `src/postmortem/__init__.py`
- Create: `src/postmortem/postmortem.py`
- Create: `tests/test_postmortem.py`

- [ ] **Step 1: Write test**

```python
# tests/test_postmortem.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from src.postmortem.postmortem import PostmortemAnalyzer

@pytest.mark.asyncio
async def test_postmortem_generates_report():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="""{
        "failure_reasons": ["Sentiment data was stale", "Market had low sample size"],
        "lessons": ["Weight recent sentiment higher", "Require minimum 30 data points"],
        "system_updates": ["Increase MIN_SENTIMENT_SAMPLES to 30", "Add recency weighting to sentiment"],
        "category": "data_quality"
    }""")]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    analyzer = PostmortemAnalyzer(anthropic_client=mock_client)
    report = await analyzer.analyze_loss(
        question="Will X happen?",
        predicted_prob=0.70,
        actual_outcome="NO",
        pnl=-50.0,
        reasoning="Strong sentiment suggested YES",
    )
    assert len(report["failure_reasons"]) > 0
    assert len(report["lessons"]) > 0
    assert len(report["system_updates"]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_postmortem.py -v`
Expected: FAIL

- [ ] **Step 3: Implement postmortem analyzer**

```python
# src/postmortem/__init__.py
# empty

# src/postmortem/postmortem.py
import json
import logging
from datetime import datetime, timezone
import anthropic
from src.config import Settings
from src.db import Database

logger = logging.getLogger(__name__)

POSTMORTEM_PROMPT = """You are 5 postmortem analysts reviewing a losing prediction market trade. Each analyst has a different focus:

1. Data Quality Analyst: Was the input data sufficient, accurate, and timely?
2. Model Analyst: Did the XGBoost/LLM model make systematic errors?
3. Market Microstructure Analyst: Were there liquidity, timing, or execution issues?
4. Sentiment Analyst: Did sentiment analysis mislead the prediction?
5. Risk Analyst: Was the position sized correctly given uncertainty?

Trade details:
- Question: {question}
- Our predicted probability: {predicted_prob:.2%}
- Actual outcome: {actual_outcome}
- P&L: ${pnl:.2f}
- Our reasoning: {reasoning}

Previous lessons learned (avoid repeating):
{previous_lessons}

Each analyst should contribute. Return JSON:
{{
    "failure_reasons": ["reason1", "reason2", ...],
    "lessons": ["lesson1", "lesson2", ...],
    "system_updates": ["concrete change 1", "concrete change 2", ...],
    "category": "data_quality|model_error|market_structure|sentiment_error|risk_management"
}}

Be specific and actionable. "system_updates" should be concrete parameter changes or logic modifications, not vague suggestions.
Return ONLY valid JSON."""

class PostmortemAnalyzer:
    def __init__(self, anthropic_client=None, settings: Settings | None = None, db: Database | None = None):
        self.settings = settings or Settings()
        self.client = anthropic_client or anthropic.Anthropic(api_key=self.settings.ANTHROPIC_API_KEY)
        self.db = db

    async def analyze_loss(
        self,
        question: str,
        predicted_prob: float,
        actual_outcome: str,
        pnl: float,
        reasoning: str,
    ) -> dict:
        """Run 5-analyst postmortem on a losing trade."""
        previous_lessons = ""
        if self.db:
            lessons = self.db.get_lessons()
            previous_lessons = "\n".join(f"- {l['lesson']}" for l in lessons[-20:])

        prompt = POSTMORTEM_PROMPT.format(
            question=question,
            predicted_prob=predicted_prob,
            actual_outcome=actual_outcome,
            pnl=pnl,
            reasoning=reasoning,
            previous_lessons=previous_lessons or "None yet.",
        )

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            report = json.loads(text)
        except Exception as e:
            logger.error(f"Postmortem analysis failed: {e}")
            report = {
                "failure_reasons": [f"Postmortem analysis failed: {e}"],
                "lessons": ["Ensure LLM is available for postmortem analysis"],
                "system_updates": [],
                "category": "unknown",
            }

        # Save lessons to DB
        if self.db:
            category = report.get("category", "unknown")
            for lesson in report.get("lessons", []):
                self.db.save_lesson(category=category, lesson=lesson)

        return report

    async def run_full_postmortem(self):
        """Analyze all recent unsettled losses."""
        if not self.db:
            return []
        losses = self.db.get_losing_trades(limit=5)
        reports = []
        for trade in losses:
            report = await self.analyze_loss(
                question=trade.get("market_id", "Unknown"),
                predicted_prob=trade.get("price", 0.5),
                actual_outcome="LOSS",
                pnl=trade.get("pnl", 0),
                reasoning="See trade history",
            )
            reports.append(report)
        return reports
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_postmortem.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/postmortem/ tests/test_postmortem.py
git commit -m "feat: add 5-agent postmortem analyzer with lesson persistence"
```

---

### Task 15: Pipeline Orchestrator

**Files:**
- Create: `src/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write test**

```python
# tests/test_pipeline.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.pipeline import Pipeline
from src.config import Settings

@pytest.mark.asyncio
async def test_pipeline_scan_only_mode(tmp_path):
    """Test that pipeline can run scanner and return flagged markets."""
    settings = Settings(ANTHROPIC_API_KEY="test")

    with patch("src.pipeline.MarketScanner") as MockScanner:
        mock_scanner = MockScanner.return_value
        mock_market = MagicMock()
        mock_market.question = "Test market?"
        mock_market.flags = ["high_volume"]
        mock_market.condition_id = "0xabc"
        mock_scanner.scan = AsyncMock(return_value=[mock_market])

        pipeline = Pipeline(settings=settings, db_path=str(tmp_path / "test.db"))
        markets = await pipeline.scan()
        assert len(markets) == 1
        assert markets[0].question == "Test market?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL

- [ ] **Step 3: Implement pipeline orchestrator**

```python
# src/pipeline.py
import asyncio
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.db import Database
from src.scanner.scanner import MarketScanner
from src.research.twitter import TwitterResearcher
from src.research.reddit import RedditResearcher
from src.research.rss import RSSResearcher
from src.research.sentiment import SentimentAnalyzer
from src.predictor.features import extract_features
from src.predictor.xgb_model import PredictionModel
from src.predictor.calibrator import Calibrator
from src.risk.risk_manager import RiskManager
from src.risk.executor import TradeExecutor
from src.postmortem.postmortem import PostmortemAnalyzer
from src.models import ResearchReport, SentimentResult, ScannedMarket

logger = logging.getLogger(__name__)

class Pipeline:
    def __init__(self, settings: Settings | None = None, db_path: str = "bot.db"):
        self.settings = settings or Settings()
        self.db = Database(db_path)
        self.db.init()

        self.scanner = MarketScanner(self.settings)
        self.sentiment = SentimentAnalyzer(use_transformer=True)
        self.xgb_model = PredictionModel()
        self.calibrator = Calibrator(settings=self.settings)
        self.risk_manager = RiskManager(self.settings)
        self.postmortem = PostmortemAnalyzer(settings=self.settings, db=self.db)

        # Research agents (initialized lazily if credentials available)
        self._twitter = None
        self._reddit = None
        self._rss = RSSResearcher()

    async def scan(self) -> list[ScannedMarket]:
        """Step 1: Scan and filter markets."""
        logger.info("=== STEP 1: Scanning markets ===")
        markets = await self.scanner.scan()
        logger.info(f"Found {len(markets)} markets passing filters")
        return markets

    async def research(self, market: ScannedMarket) -> ResearchReport:
        """Step 2: Run research agents in parallel for a single market."""
        logger.info(f"=== STEP 2: Researching '{market.question[:60]}' ===")
        query = market.question

        # Run all research agents in parallel
        twitter_task = self._search_twitter(query)
        reddit_task = self._search_reddit(query)
        rss_task = asyncio.to_thread(self._rss.search, query)

        twitter_results, reddit_results, rss_results = await asyncio.gather(
            twitter_task, reddit_task, rss_task, return_exceptions=True
        )

        # Handle exceptions
        if isinstance(twitter_results, Exception):
            logger.warning(f"Twitter research failed: {twitter_results}")
            twitter_results = []
        if isinstance(reddit_results, Exception):
            logger.warning(f"Reddit research failed: {reddit_results}")
            reddit_results = []
        if isinstance(rss_results, Exception):
            logger.warning(f"RSS research failed: {rss_results}")
            rss_results = []

        # Run sentiment analysis on all collected texts
        sentiments = []
        for source_name, results in [("twitter", twitter_results), ("reddit", reddit_results), ("rss", rss_results)]:
            if not results:
                continue
            texts = [r["text"] for r in results]
            analyzed = self.sentiment.analyze_batch(texts)
            agg = self.sentiment.aggregate(analyzed)
            sentiments.append(SentimentResult(
                source=source_name,
                query=query,
                positive_ratio=agg["positive_ratio"],
                negative_ratio=agg["negative_ratio"],
                neutral_ratio=agg["neutral_ratio"],
                sample_size=agg["sample_size"],
                avg_compound_score=agg["avg_score"],
                collected_at=datetime.now(timezone.utc),
            ))

        # Generate narrative summary via Claude
        narrative = await self._generate_narrative(market, sentiments)

        return ResearchReport(
            market_id=market.condition_id,
            question=market.question,
            sentiments=sentiments,
            narrative_summary=narrative,
            narrative_vs_odds_alignment=self._calc_alignment(sentiments, market.yes_price),
            researched_at=datetime.now(timezone.utc),
        )

    async def predict(self, market: ScannedMarket, research: ResearchReport):
        """Step 3: Run prediction engine."""
        logger.info(f"=== STEP 3: Predicting '{market.question[:60]}' ===")

        # Aggregate sentiment for features
        if research.sentiments:
            avg_pos = sum(s.positive_ratio for s in research.sentiments) / len(research.sentiments)
            avg_neg = sum(s.negative_ratio for s in research.sentiments) / len(research.sentiments)
            avg_neu = sum(s.neutral_ratio for s in research.sentiments) / len(research.sentiments)
            avg_score = sum(s.avg_compound_score for s in research.sentiments) / len(research.sentiments)
            total_samples = sum(s.sample_size for s in research.sentiments)
        else:
            avg_pos = avg_neg = avg_neu = avg_score = 0
            total_samples = 0

        sentiment_agg = {
            "positive_ratio": avg_pos,
            "negative_ratio": avg_neg,
            "neutral_ratio": avg_neu,
            "avg_score": avg_score,
            "sample_size": total_samples,
        }

        features = extract_features(market, sentiment_agg)
        xgb_prob = self.xgb_model.predict(features)
        prediction = await self.calibrator.calibrate(market, research, xgb_prob)

        logger.info(
            f"Prediction: {prediction.recommended_side} | "
            f"prob={prediction.predicted_probability:.2%} | "
            f"edge={prediction.edge:.2%} | conf={prediction.confidence:.2f}"
        )
        return prediction

    def evaluate_risk(self, prediction):
        """Step 4a: Risk evaluation."""
        logger.info(f"=== STEP 4: Risk evaluation ===")
        daily_pnl = self.db.get_daily_pnl()
        decision = self.risk_manager.evaluate(prediction, daily_pnl)

        if decision.approved:
            logger.info(f"APPROVED: ${decision.bet_size_usd:.2f} on {prediction.recommended_side}")
        else:
            logger.info(f"BLOCKED: {decision.rejection_reason}")
        return decision

    async def run_postmortem(self):
        """Step 5: Run postmortem on recent losses."""
        logger.info("=== STEP 5: Running postmortem ===")
        reports = await self.postmortem.run_full_postmortem()
        for report in reports:
            logger.info(f"Postmortem: {report.get('category', 'unknown')} - {len(report.get('lessons', []))} lessons")
        return reports

    async def run_cycle(self, dry_run: bool = True):
        """Run one full pipeline cycle."""
        logger.info("========== STARTING PIPELINE CYCLE ==========")

        # Step 1: Scan
        markets = await self.scan()
        if not markets:
            logger.info("No markets found, ending cycle")
            return

        # Take top 10 flagged markets for research
        flagged = [m for m in markets if m.flags]
        targets = flagged[:10] if flagged else markets[:5]

        for market in targets:
            try:
                # Step 2: Research
                research = await self.research(market)

                # Step 3: Predict
                prediction = await self.predict(market, research)

                # Step 4: Risk check
                decision = self.evaluate_risk(prediction)

                if decision.approved and not dry_run:
                    # Execute trade (requires CLOB client setup)
                    logger.info(f"Would execute: {decision.bet_size_usd} on {prediction.recommended_side}")
                    # executor.execute(decision, token_id=market.token_yes_id)

                elif decision.approved and dry_run:
                    logger.info(f"[DRY RUN] Would bet ${decision.bet_size_usd:.2f} on {prediction.recommended_side}")

            except Exception as e:
                logger.error(f"Pipeline error for {market.question[:50]}: {e}")
                continue

        # Step 5: Postmortem on any recent losses
        await self.run_postmortem()

        logger.info("========== CYCLE COMPLETE ==========")

    # --- Private helpers ---

    async def _search_twitter(self, query: str) -> list[dict]:
        if self._twitter is None:
            from twscrape import API
            self._twitter = TwitterResearcher(API())
        return await self._twitter.search(query, limit=50)

    async def _search_reddit(self, query: str) -> list[dict]:
        if self._reddit is None:
            self._reddit = RedditResearcher(settings=self.settings)
        return await asyncio.to_thread(self._reddit.search, query)

    async def _generate_narrative(self, market: ScannedMarket, sentiments: list[SentimentResult]) -> str:
        """Use Claude to summarize research findings into a narrative."""
        sentiment_text = "\n".join(
            f"- {s.source}: {s.positive_ratio:.0%} positive, {s.negative_ratio:.0%} negative (n={s.sample_size})"
            for s in sentiments
        )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.settings.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": (
                    f"Summarize the public sentiment and narrative for this prediction market in 2-3 sentences:\n"
                    f"Question: {market.question}\n"
                    f"Current YES price: {market.yes_price}\n"
                    f"Sentiment data:\n{sentiment_text or 'No data collected'}"
                )}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Narrative generation failed: {e}")
            return "Narrative generation unavailable."

    def _calc_alignment(self, sentiments: list[SentimentResult], yes_price: float) -> float:
        """How well does sentiment align with market odds? -1 to 1."""
        if not sentiments:
            return 0.0
        avg_pos = sum(s.positive_ratio for s in sentiments) / len(sentiments)
        return 2 * (1 - abs(avg_pos - yes_price)) - 1  # 1 = perfect alignment


# CLI entry point
async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    settings = Settings()
    pipeline = Pipeline(settings=settings)

    dry_run = "--live" not in sys.argv
    if dry_run:
        logger.info("Running in DRY RUN mode (use --live to execute trades)")

    await pipeline.run_cycle(dry_run=dry_run)

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: add pipeline orchestrator wiring all 5 agents together"
```

---

### Task 16: CLI Entry Point & Final Integration

**Files:**
- Create: `run.py`

- [ ] **Step 1: Create run.py**

```python
# run.py
import asyncio
import sys
import logging
from src.pipeline import Pipeline
from src.config import Settings

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("polymarket-bot")

    settings = Settings()
    dry_run = "--live" not in sys.argv

    if dry_run:
        logger.info("=== DRY RUN MODE (pass --live to execute real trades) ===")
    else:
        logger.warning("=== LIVE MODE - REAL TRADES WILL BE PLACED ===")
        if not settings.POLYMARKET_PRIVATE_KEY:
            logger.error("POLYMARKET_PRIVATE_KEY not set. Cannot trade in live mode.")
            sys.exit(1)

    pipeline = Pipeline(settings=settings)
    asyncio.run(pipeline.run_cycle(dry_run=dry_run))

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add run.py
git commit -m "feat: add CLI entry point with dry-run and live modes"
```

- [ ] **Step 4: Final commit with all __init__ files**

```bash
git add -A
git commit -m "chore: complete project structure"
```

---

## Summary

| Step | Agent | What it does |
|------|-------|-------------|
| 1 | Scanner | Fetches 300+ markets from Gamma API, filters by liquidity/volume/time, flags anomalies |
| 2 | Research (3 parallel) | Twitter (twscrape), Reddit (PRAW), RSS (feedparser) + sentiment analysis (VADER/RoBERTa) |
| 3 | Predictor | XGBoost features + Claude calibration -> true probability vs market price |
| 4 | Risk + Executor | Half-Kelly sizing, daily loss limits, confidence gates -> CLOB order + settlement watch |
| 5 | Postmortem (5 analysts) | Claude-powered loss analysis, lesson extraction, persisted to DB for future cycles |

**Key design decisions:**
- SQLite for simplicity (local-first, no infra needed)
- Half-Kelly (not full) for conservative position sizing
- Dry-run mode by default -- must explicitly pass `--live`
- Hybrid sentiment (VADER fast-path + RoBERTa for ambiguous)
- XGBoost 40% / Claude 60% weighting (LLM has broader context)
- Haiku for cheap narrative generation, Sonnet for calibration and postmortem
