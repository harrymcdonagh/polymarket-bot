# Two-Track Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 free data sources (3 text, 3 structured) and replace VADER ambiguous-text path with Haiku sentiment, expanding XGBoost from 20 to 33 features.

**Architecture:** Two parallel tracks — Track 1 sends text through sentiment analysis, Track 2 returns numeric features directly. Both merge at feature extraction. Haiku replaces RoBERTa for ambiguous texts in sentiment analysis.

**Tech Stack:** Python 3.11+, httpx, asyncio, anthropic SDK, xgboost, vaderSentiment, feedparser, pydantic-settings

**Spec:** `docs/superpowers/specs/2026-03-16-two-track-data-pipeline-design.md`

---

## File Structure

**New files (8):**
| File | Responsibility |
|------|---------------|
| `src/research/metaculus.py` | ResearchSource: Metaculus community forecasts |
| `src/research/predictit.py` | ResearchSource: PredictIt/Manifold market prices |
| `src/research/wikipedia.py` | ResearchSource: Wikipedia Current Events headlines |
| `src/research/structured_base.py` | ABC for structured (numeric) data sources |
| `src/research/structured_pipeline.py` | Orchestrator for structured sources |
| `src/research/clob.py` | StructuredDataSource: Polymarket CLOB order book |
| `src/research/coingecko.py` | StructuredDataSource: CoinGecko crypto prices |
| `src/research/fred.py` | StructuredDataSource: FRED economic indicators |

**New test files (7):**
| File | Tests |
|------|-------|
| `tests/test_metaculus.py` | Metaculus source: search, availability, error handling |
| `tests/test_predictit.py` | PredictIt source: search, matching, error handling |
| `tests/test_wikipedia.py` | Wikipedia source: search, filtering, error handling |
| `tests/test_structured_pipeline.py` | StructuredDataPipeline + StructuredDataSource ABC |
| `tests/test_clob.py` | CLOB source: fetch, features, error handling |
| `tests/test_coingecko.py` | CoinGecko source: fetch, activation, caching |
| `tests/test_fred.py` | FRED source: fetch, activation, caching |

**Modified files (7):**
| File | Changes |
|------|---------|
| `src/research/sentiment.py` | Haiku for ambiguous texts, async analyze_batch |
| `src/research/pipeline.py` | Register 3 new sources, pass market_question |
| `src/predictor/features.py` | Accept structured_data, add 13 features |
| `src/predictor/xgb_model.py` | FEATURE_ORDER 20→33 |
| `src/predictor/trainer.py` | Add 13 new feature defaults |
| `src/pipeline.py` | Wire structured pipeline, parallel tracks |
| `src/config.py` | New settings: sentiment LLM, FRED key, source weights |

---

## Chunk 1: Structured Data Infrastructure + CLOB Source

### Task 1: StructuredDataSource ABC

**Files:**
- Create: `src/research/structured_base.py`
- Create: `tests/test_structured_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_structured_pipeline.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.research.structured_base import StructuredDataSource


class FakeSource(StructuredDataSource):
    name = "fake"

    async def fetch(self, market) -> dict[str, float]:
        return {"fake_value": 1.0}

    def is_available(self) -> bool:
        return True


def test_structured_source_abc():
    source = FakeSource()
    assert source.name == "fake"
    assert source.is_available() is True


@pytest.mark.asyncio
async def test_structured_source_fetch():
    source = FakeSource()
    market = MagicMock()
    result = await source.fetch(market)
    assert result == {"fake_value": 1.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_structured_pipeline.py::test_structured_source_abc -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.research.structured_base'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/research/structured_base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from src.models import ScannedMarket


class StructuredDataSource(ABC):
    """Base class for structured (numeric) data sources that skip sentiment analysis."""

    name: str

    @abstractmethod
    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        """Return named numeric features. Empty dict if unavailable."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this source is configured and usable."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_structured_pipeline.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/research/structured_base.py tests/test_structured_pipeline.py
git commit -m "feat: add StructuredDataSource ABC"
```

---

### Task 2: StructuredDataPipeline Orchestrator

**Files:**
- Create: `src/research/structured_pipeline.py`
- Modify: `tests/test_structured_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_structured_pipeline.py`:

```python
from src.research.structured_pipeline import StructuredDataPipeline


class FailingSource(StructuredDataSource):
    name = "failing"

    async def fetch(self, market) -> dict[str, float]:
        raise RuntimeError("API down")

    def is_available(self) -> bool:
        return True


class UnavailableSource(StructuredDataSource):
    name = "unavailable"

    async def fetch(self, market) -> dict[str, float]:
        return {"should_not_appear": 99.0}

    def is_available(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_pipeline_merges_sources():
    """Multiple sources merge their feature dicts."""
    class SourceA(StructuredDataSource):
        name = "a"
        async def fetch(self, market): return {"a_val": 1.0}
        def is_available(self): return True

    class SourceB(StructuredDataSource):
        name = "b"
        async def fetch(self, market): return {"b_val": 2.0}
        def is_available(self): return True

    pipeline = StructuredDataPipeline(sources=[SourceA(), SourceB()])
    result = await pipeline.fetch(MagicMock())
    assert result == {"a_val": 1.0, "b_val": 2.0}


@pytest.mark.asyncio
async def test_pipeline_handles_failure():
    """Failed source returns empty dict, others still contribute."""
    pipeline = StructuredDataPipeline(sources=[FakeSource(), FailingSource()])
    result = await pipeline.fetch(MagicMock())
    assert result == {"fake_value": 1.0}


@pytest.mark.asyncio
async def test_pipeline_skips_unavailable():
    """Unavailable sources are not called."""
    pipeline = StructuredDataPipeline(sources=[FakeSource(), UnavailableSource()])
    result = await pipeline.fetch(MagicMock())
    assert "should_not_appear" not in result
    assert result == {"fake_value": 1.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_structured_pipeline.py::test_pipeline_merges_sources -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/research/structured_pipeline.py
from __future__ import annotations

import asyncio
import logging

from src.research.structured_base import StructuredDataSource
from src.models import ScannedMarket

logger = logging.getLogger(__name__)


class StructuredDataPipeline:
    """Orchestrates structured data sources in parallel, merges feature dicts."""

    def __init__(self, sources: list[StructuredDataSource], timeout: float = 10.0):
        self.sources = sources
        self.timeout = timeout

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        available = [s for s in self.sources if s.is_available()]
        if not available:
            return {}

        tasks = [self._fetch_with_timeout(s, market) for s in available]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: dict[str, float] = {}
        for source, result in zip(available, results):
            if isinstance(result, Exception):
                logger.warning(f"Structured source '{source.name}' failed: {result}")
                continue
            merged.update(result)

        return merged

    async def _fetch_with_timeout(
        self, source: StructuredDataSource, market: ScannedMarket
    ) -> dict[str, float]:
        try:
            return await asyncio.wait_for(source.fetch(market), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Structured source '{source.name}' timed out after {self.timeout}s")
            return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_structured_pipeline.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/research/structured_pipeline.py tests/test_structured_pipeline.py
git commit -m "feat: add StructuredDataPipeline orchestrator"
```

---

### Task 3: CLOB Order Book Source

**Files:**
- Create: `src/research/clob.py`
- Create: `tests/test_clob.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clob.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.research.clob import CLOBSource


@pytest.fixture
def clob():
    return CLOBSource()


def test_clob_is_available(clob):
    assert clob.is_available() is True


def test_clob_name(clob):
    assert clob.name == "clob"


@pytest.mark.asyncio
async def test_clob_fetch_returns_features(clob):
    """CLOB source returns 5 features from order book data."""
    market = MagicMock()
    market.token_yes_id = "token-123"
    market.yes_price = 0.60

    mock_book = {
        "bids": [
            {"price": "0.58", "size": "100"},
            {"price": "0.57", "size": "200"},
            {"price": "0.56", "size": "150"},
        ],
        "asks": [
            {"price": "0.62", "size": "80"},
            {"price": "0.63", "size": "120"},
            {"price": "0.64", "size": "100"},
        ],
    }

    mock_resp = MagicMock()  # MagicMock, not AsyncMock — httpx .json() is sync
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_book

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await clob.fetch(market)

    assert "clob_bid_ask_spread" in result
    assert "clob_buy_depth" in result
    assert "clob_sell_depth" in result
    assert "clob_imbalance" in result
    assert "clob_midpoint_vs_gamma" in result
    assert len(result) == 5
    # Spread = lowest ask - highest bid = 0.62 - 0.58 = 0.04
    assert result["clob_bid_ask_spread"] == pytest.approx(0.04)


@pytest.mark.asyncio
async def test_clob_fetch_empty_on_error(clob):
    """CLOB source returns empty dict on API error."""
    market = MagicMock()
    market.token_yes_id = "token-123"
    market.yes_price = 0.60

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.json.side_effect = Exception("Server error")

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await clob.fetch(market)

    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_clob.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/research/clob.py
from __future__ import annotations

import logging
import httpx

from src.research.structured_base import StructuredDataSource
from src.models import ScannedMarket

logger = logging.getLogger(__name__)

CLOB_BOOK_URL = "https://clob.polymarket.com/book"


class CLOBSource(StructuredDataSource):
    """Fetches real-time order book depth from Polymarket CLOB REST API."""

    name = "clob"

    def is_available(self) -> bool:
        return True  # Public endpoint, no auth needed

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    CLOB_BOOK_URL,
                    params={"token_id": market.token_yes_id},
                )
                if resp.status_code != 200:
                    logger.warning(f"CLOB API returned {resp.status_code}")
                    return {}

                book = resp.json()
                return self._extract_features(book, market.yes_price)
        except Exception as e:
            logger.warning(f"CLOB fetch failed: {e}")
            return {}

    def _extract_features(self, book: dict, gamma_price: float) -> dict[str, float]:
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            return {}

        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])
        midpoint = (best_bid + best_ask) / 2

        # Depth within 5% of midpoint
        buy_depth = sum(
            float(b["size"]) for b in bids
            if float(b["price"]) >= midpoint * 0.95
        )
        sell_depth = sum(
            float(a["size"]) for a in asks
            if float(a["price"]) <= midpoint * 1.05
        )

        total_depth = buy_depth + sell_depth
        imbalance = buy_depth / total_depth if total_depth > 0 else 0.5

        return {
            "clob_bid_ask_spread": best_ask - best_bid,
            "clob_buy_depth": buy_depth,
            "clob_sell_depth": sell_depth,
            "clob_imbalance": imbalance,
            "clob_midpoint_vs_gamma": midpoint - gamma_price,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_clob.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/research/clob.py tests/test_clob.py
git commit -m "feat: add CLOB order book structured data source"
```

---

### Task 4: CoinGecko Crypto Source

**Files:**
- Create: `src/research/coingecko.py`
- Create: `tests/test_coingecko.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_coingecko.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.research.coingecko import CoinGeckoSource


@pytest.fixture
def cg():
    return CoinGeckoSource()


def test_coingecko_is_available(cg):
    assert cg.is_available() is True


def test_coingecko_name(cg):
    assert cg.name == "coingecko"


@pytest.mark.asyncio
async def test_coingecko_crypto_market(cg):
    """Returns crypto features for a BTC-related market."""
    market = MagicMock()
    market.question = "Will Bitcoin exceed $100k by end of 2026?"

    mock_resp = MagicMock()  # MagicMock — httpx .json() is sync
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "bitcoin": {
            "usd": 95000,
            "usd_24h_change": 2.5,
            "usd_market_cap": 1800000000000,
        }
    }

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await cg.fetch(market)

    assert result["crypto_is_relevant"] == 1.0
    assert result["crypto_price_usd"] == 95000
    assert result["crypto_24h_change"] == 2.5
    assert result["crypto_market_cap"] == 1800000000000


@pytest.mark.asyncio
async def test_coingecko_non_crypto_market(cg):
    """Returns zeros for non-crypto markets without making API calls."""
    market = MagicMock()
    market.question = "Will the US enter a recession in 2026?"

    result = await cg.fetch(market)

    assert result["crypto_is_relevant"] == 0.0
    assert result["crypto_price_usd"] == 0.0
    assert result["crypto_24h_change"] == 0.0
    assert result["crypto_market_cap"] == 0.0


@pytest.mark.asyncio
async def test_coingecko_api_error(cg):
    """Returns empty dict on API error."""
    market = MagicMock()
    market.question = "Will Bitcoin hit $200k?"

    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        result = await cg.fetch(market)

    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coingecko.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/research/coingecko.py
from __future__ import annotations

import logging
import time
import re

import httpx

from src.research.structured_base import StructuredDataSource
from src.models import ScannedMarket

logger = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

# Maps keyword patterns to CoinGecko coin IDs
CRYPTO_KEYWORDS: dict[str, str] = {
    r"\bbitcoin\b|\bbtc\b": "bitcoin",
    r"\bethereum\b|\beth\b": "ethereum",
    r"\bsolana\b|\bsol\b": "solana",
    r"\bdogecoin\b|\bdoge\b": "dogecoin",
    r"\bcardano\b|\bada\b": "cardano",
    r"\bripple\b|\bxrp\b": "ripple",
    r"\bpolygon\b|\bmatic\b": "matic-network",
}

CACHE_TTL = 300  # 5 minutes


class CoinGeckoSource(StructuredDataSource):
    """Fetches crypto prices from CoinGecko. Only activates for crypto markets."""

    name = "coingecko"

    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}

    def is_available(self) -> bool:
        return True  # Free API, no key needed

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        coin_id = self._detect_crypto(market.question)
        if not coin_id:
            return {
                "crypto_price_usd": 0.0,
                "crypto_24h_change": 0.0,
                "crypto_market_cap": 0.0,
                "crypto_is_relevant": 0.0,
            }

        try:
            data = await self._fetch_price(coin_id)
            if not data:
                return {}

            return {
                "crypto_price_usd": data.get("usd", 0.0),
                "crypto_24h_change": data.get("usd_24h_change", 0.0),
                "crypto_market_cap": data.get("usd_market_cap", 0.0),
                "crypto_is_relevant": 1.0,
            }
        except Exception as e:
            logger.warning(f"CoinGecko fetch failed: {e}")
            return {}

    def _detect_crypto(self, question: str) -> str | None:
        q_lower = question.lower()
        # Also check for generic "crypto" keyword
        if re.search(r"\bcrypto\b|\bcryptocurrency\b", q_lower):
            return "bitcoin"  # Default to BTC for generic crypto questions
        for pattern, coin_id in CRYPTO_KEYWORDS.items():
            if re.search(pattern, q_lower):
                return coin_id
        return None

    async def _fetch_price(self, coin_id: str) -> dict | None:
        # Check cache
        now = time.time()
        if coin_id in self._cache:
            cached_at, data = self._cache[coin_id]
            if now - cached_at < CACHE_TTL:
                return data

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                COINGECKO_URL,
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"CoinGecko API returned {resp.status_code}")
                return None

            data = resp.json().get(coin_id)
            if data:
                self._cache[coin_id] = (now, data)
            return data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coingecko.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/research/coingecko.py tests/test_coingecko.py
git commit -m "feat: add CoinGecko crypto structured data source"
```

---

### Task 5: FRED Economic Source

**Files:**
- Create: `src/research/fred.py`
- Create: `tests/test_fred.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fred.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.research.fred import FREDSource


@pytest.fixture
def fred():
    return FREDSource(api_key="test-key")


@pytest.fixture
def fred_no_key():
    return FREDSource(api_key="")


def test_fred_available_with_key(fred):
    assert fred.is_available() is True


def test_fred_unavailable_without_key(fred_no_key):
    assert fred_no_key.is_available() is False


def test_fred_name(fred):
    assert fred.name == "fred"


@pytest.mark.asyncio
async def test_fred_economic_market(fred):
    """Returns FRED features for an economic market."""
    market = MagicMock()
    market.question = "Will the US unemployment rate exceed 5% in 2026?"

    def mock_get(url, **kwargs):
        resp = MagicMock()  # MagicMock — httpx .json() is sync
        resp.status_code = 200
        series_id = kwargs.get("params", {}).get("series_id", "")
        if series_id == "UNRATE":
            resp.json.return_value = {"observations": [{"value": "4.2"}]}
        elif series_id == "CPIAUCSL":
            resp.json.return_value = {"observations": [{"value": "310.5"}]}
        elif series_id == "FEDFUNDS":
            resp.json.return_value = {"observations": [{"value": "5.25"}]}
        return resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await fred.fetch(market)

    assert result["fred_is_relevant"] == 1.0
    assert result["fred_unemployment"] == 4.2
    assert result["fred_cpi_latest"] == 310.5
    assert result["fred_fed_funds_rate"] == 5.25


@pytest.mark.asyncio
async def test_fred_non_economic_market(fred):
    """Returns zeros for non-economic markets without API calls."""
    market = MagicMock()
    market.question = "Will the Lakers win the NBA championship?"

    result = await fred.fetch(market)

    assert result["fred_is_relevant"] == 0.0
    assert result["fred_unemployment"] == 0.0


@pytest.mark.asyncio
async def test_fred_api_error(fred):
    """Returns empty dict on API error."""
    market = MagicMock()
    market.question = "Will inflation exceed 5%?"

    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        result = await fred.fetch(market)

    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fred.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/research/fred.py
from __future__ import annotations

import logging
import re
import time

import httpx

from src.research.structured_base import StructuredDataSource
from src.models import ScannedMarket

logger = logging.getLogger(__name__)

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"

ECONOMIC_KEYWORDS = re.compile(
    r"\binflation\b|\bcpi\b|\binterest rate\b|\bfed\b|\bfederal reserve\b|"
    r"\bunemployment\b|\brecession\b|\bgdp\b|\beconomy\b|\beconomic\b",
    re.IGNORECASE,
)

SERIES_IDS = {
    "CPIAUCSL": "fred_cpi_latest",
    "FEDFUNDS": "fred_fed_funds_rate",
    "UNRATE": "fred_unemployment",
}

CACHE_TTL = 21600  # 6 hours — economic data updates monthly/quarterly


class FREDSource(StructuredDataSource):
    """Fetches key economic indicators from FRED. Requires API key."""

    name = "fred"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._cache: dict[str, tuple[float, float]] = {}  # series_id -> (timestamp, value)

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        if not ECONOMIC_KEYWORDS.search(market.question):
            return {
                "fred_cpi_latest": 0.0,
                "fred_fed_funds_rate": 0.0,
                "fred_unemployment": 0.0,
                "fred_is_relevant": 0.0,
            }

        try:
            features: dict[str, float] = {}
            async with httpx.AsyncClient(timeout=10) as client:
                for series_id, feature_name in SERIES_IDS.items():
                    value = await self._fetch_series(client, series_id)
                    features[feature_name] = value

            features["fred_is_relevant"] = 1.0
            return features
        except Exception as e:
            logger.warning(f"FRED fetch failed: {e}")
            return {}

    async def _fetch_series(self, client: httpx.AsyncClient, series_id: str) -> float:
        # Check cache
        now = time.time()
        if series_id in self._cache:
            cached_at, value = self._cache[series_id]
            if now - cached_at < CACHE_TTL:
                return value

        resp = await client.get(
            FRED_API_URL,
            params={
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            },
        )
        if resp.status_code != 200:
            logger.warning(f"FRED API returned {resp.status_code} for {series_id}")
            return 0.0

        observations = resp.json().get("observations", [])
        if not observations:
            return 0.0

        value_str = observations[0].get("value", "0")
        try:
            value = float(value_str)
        except (ValueError, TypeError):
            value = 0.0

        self._cache[series_id] = (now, value)
        return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fred.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/research/fred.py tests/test_fred.py
git commit -m "feat: add FRED economic structured data source"
```

---

## Chunk 2: New Text Sources (Track 1)

> **Note:** These sources are standalone modules. Pipeline registration (adding them to `ResearchPipeline` and wiring config weights) happens in Chunk 3, Task 12.

### Task 6: Metaculus Source

**Files:**
- Create: `src/research/metaculus.py`
- Create: `tests/test_metaculus.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_metaculus.py
import pytest
from unittest.mock import AsyncMock, patch
from src.research.metaculus import MetaculusSource


@pytest.fixture
def metaculus():
    return MetaculusSource()


def test_metaculus_is_available(metaculus):
    assert metaculus.is_available() is True


def test_metaculus_name(metaculus):
    assert metaculus.name == "metaculus"


@pytest.mark.asyncio
async def test_metaculus_search(metaculus):
    """Returns synthetic text from Metaculus community forecasts."""
    mock_resp = MagicMock()  # MagicMock — httpx .json() is sync
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {
                "title": "Will X happen by 2026?",
                "community_prediction": {"full": {"q2": 0.73}},
                "number_of_forecasters": 847,
                "page_url": "/questions/12345/",
            }
        ]
    }

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await metaculus.search("X happen 2026")

    assert len(results) == 1
    assert "73%" in results[0].text
    assert "847" in results[0].text
    assert results[0].source == "metaculus"
    assert results[0].weight == 0.9


@pytest.mark.asyncio
async def test_metaculus_empty_on_error(metaculus):
    """Returns empty list on API error."""
    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        results = await metaculus.search("anything")

    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metaculus.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/research/metaculus.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from src.research.base import ResearchSource, ResearchResult

logger = logging.getLogger(__name__)

METACULUS_API = "https://www.metaculus.com/api/questions/"


class MetaculusSource(ResearchSource):
    """Fetches community forecasts from Metaculus superforecasters."""

    name = "metaculus"

    def __init__(self, weight: float = 0.9):
        self.default_weight = weight

    def is_available(self) -> bool:
        return True  # No auth needed

    async def search(self, query: str) -> list[ResearchResult]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    METACULUS_API,
                    params={
                        "search": query,
                        "status": "open",
                        "type": "forecast",
                        "limit": 5,
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"Metaculus API returned {resp.status_code}")
                    return []

                data = resp.json()
                questions = data.get("results", [])

            results = []
            for q in questions:
                community = q.get("community_prediction", {})
                median = None
                if isinstance(community, dict):
                    full = community.get("full", {})
                    if isinstance(full, dict):
                        median = full.get("q2")

                if median is None:
                    continue

                forecasters = q.get("number_of_forecasters", 0)
                title = q.get("title", "Unknown")
                pct = round(median * 100)
                page_url = q.get("page_url", "")
                link = f"https://www.metaculus.com{page_url}" if page_url else ""

                text = (
                    f"Metaculus community predicts {pct}% likelihood "
                    f"({forecasters} forecasters): {title}"
                )

                results.append(ResearchResult(
                    text=text,
                    link=link,
                    published=datetime.now(timezone.utc),
                    source="metaculus",
                    weight=self.default_weight,
                ))

            return results
        except Exception as e:
            logger.warning(f"Metaculus search failed: {e}")
            return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metaculus.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/research/metaculus.py tests/test_metaculus.py
git commit -m "feat: add Metaculus community forecast text source"
```

---

### Task 7: PredictIt / Manifold Source

**Files:**
- Create: `src/research/predictit.py`
- Create: `tests/test_predictit.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_predictit.py
import pytest
from unittest.mock import AsyncMock, patch
from src.research.predictit import PredictItSource


@pytest.fixture
def predictit():
    return PredictItSource()


def test_predictit_is_available(predictit):
    assert predictit.is_available() is True


def test_predictit_name(predictit):
    assert predictit.name == "predictit"


@pytest.mark.asyncio
async def test_predictit_search_with_match(predictit):
    """Returns synthetic text for matching markets."""
    mock_resp = MagicMock()  # MagicMock — httpx .json() is sync
    mock_resp.status_code = 200
    # Manifold Markets API response format
    mock_resp.json.return_value = [
        {
            "question": "Will Biden win the 2024 election?",
            "probability": 0.42,
            "url": "https://manifold.markets/test",
            "uniqueBettorCount": 150,
        }
    ]

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await predictit.search("Biden win 2024 election")

    assert len(results) >= 1
    assert "42%" in results[0].text
    assert results[0].source == "predictit"
    assert results[0].weight == 0.85


@pytest.mark.asyncio
async def test_predictit_search_no_match(predictit):
    """Returns empty when no markets match."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await predictit.search("totally unrelated query")

    assert results == []


@pytest.mark.asyncio
async def test_predictit_error_returns_empty(predictit):
    """Returns empty list on API error."""
    with patch("httpx.AsyncClient.get", side_effect=Exception("network error")):
        results = await predictit.search("any query")

    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictit.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Note: PredictIt shut down in 2023. We use Manifold Markets API as the fallback (same concept: cross-reference prediction market prices). The source name stays `predictit` for config compatibility.

```python
# src/research/predictit.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from src.research.base import ResearchSource, ResearchResult

logger = logging.getLogger(__name__)

# Manifold Markets API (free, no auth, active)
MANIFOLD_SEARCH_URL = "https://api.manifold.markets/v0/search-markets"


class PredictItSource(ResearchSource):
    """Fetches prediction market prices from Manifold Markets for cross-reference.

    Named PredictIt for historical reasons; uses Manifold Markets API
    since PredictIt shut down in 2023.
    """

    name = "predictit"

    def __init__(self, weight: float = 0.85):
        self.default_weight = weight

    def is_available(self) -> bool:
        return True  # No auth needed

    async def search(self, query: str) -> list[ResearchResult]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    MANIFOLD_SEARCH_URL,
                    params={"term": query, "limit": 5},
                )
                if resp.status_code != 200:
                    logger.warning(f"Manifold API returned {resp.status_code}")
                    return []

                markets = resp.json()

            results = []
            for m in markets[:3]:  # Top 3 matches
                question = m.get("question", "")
                prob = m.get("probability")
                if prob is None:
                    continue

                pct = round(prob * 100)
                bettors = m.get("uniqueBettorCount", 0)
                url = m.get("url", "")

                text = (
                    f"Manifold Markets prices this at {pct}% YES "
                    f"({bettors} traders): {question}"
                )

                results.append(ResearchResult(
                    text=text,
                    link=url,
                    published=datetime.now(timezone.utc),
                    source="predictit",
                    weight=self.default_weight,
                ))

            return results
        except Exception as e:
            logger.warning(f"PredictIt/Manifold search failed: {e}")
            return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictit.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/research/predictit.py tests/test_predictit.py
git commit -m "feat: add PredictIt/Manifold prediction market text source"
```

---

### Task 8: Wikipedia Current Events Source

**Files:**
- Create: `src/research/wikipedia.py`
- Create: `tests/test_wikipedia.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_wikipedia.py
import pytest
from unittest.mock import AsyncMock, patch
from src.research.wikipedia import WikipediaSource


@pytest.fixture
def wiki():
    return WikipediaSource()


def test_wikipedia_is_available(wiki):
    assert wiki.is_available() is True


def test_wikipedia_name(wiki):
    assert wiki.name == "wikipedia"


@pytest.mark.asyncio
async def test_wikipedia_search(wiki):
    """Returns matching headlines from Wikipedia Current Events."""
    html = """
    <ul>
        <li>Biden signs new executive order on AI regulation</li>
        <li>Earthquake strikes Turkey, 20 casualties reported</li>
        <li>SpaceX launches Starship test flight</li>
    </ul>
    """
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.text = html

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await wiki.search("Biden executive order AI")

    assert len(results) >= 1
    assert "Biden" in results[0].text
    assert results[0].source == "wikipedia"


@pytest.mark.asyncio
async def test_wikipedia_no_matches(wiki):
    """Returns empty when no headlines match."""
    html = "<ul><li>Unrelated headline about football</li></ul>"
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.text = html

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        results = await wiki.search("quantum computing breakthrough")

    assert results == []


@pytest.mark.asyncio
async def test_wikipedia_error_returns_empty(wiki):
    """Returns empty list on API error."""
    with patch("httpx.AsyncClient.get", side_effect=Exception("timeout")):
        results = await wiki.search("anything")

    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wikipedia.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/research/wikipedia.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser

import httpx

from src.research.base import ResearchSource, ResearchResult

logger = logging.getLogger(__name__)

WIKIPEDIA_CURRENT_EVENTS = (
    "https://en.wikipedia.org/api/rest_v1/page/html/Portal%3ACurrent_events"
)


class _ListItemParser(HTMLParser):
    """Extract text content from <li> elements."""

    def __init__(self):
        super().__init__()
        self.items: list[str] = []
        self._in_li = False
        self._current = ""

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self._in_li = True
            self._current = ""

    def handle_endtag(self, tag):
        if tag == "li" and self._in_li:
            text = self._current.strip()
            if text:
                self.items.append(text)
            self._in_li = False

    def handle_data(self, data):
        if self._in_li:
            self._current += data


def _is_relevant(title: str, query: str, threshold: float = 0.4) -> bool:
    """Check if a headline is relevant to a query via fuzzy matching.

    Same logic as rss.py _is_relevant().
    """
    title_lower = title.lower()
    query_lower = query.lower()
    if query_lower in title_lower:
        return True
    query_words = query_lower.split()
    if any(word in title_lower for word in query_words if len(word) > 3):
        return True
    return SequenceMatcher(None, title_lower, query_lower).ratio() >= threshold


class WikipediaSource(ResearchSource):
    """Fetches today's current events from Wikipedia Portal."""

    name = "wikipedia"

    def __init__(self, weight: float = 0.7):
        self.default_weight = weight

    def is_available(self) -> bool:
        return True  # No auth needed

    async def search(self, query: str) -> list[ResearchResult]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(WIKIPEDIA_CURRENT_EVENTS)
                if resp.status_code != 200:
                    logger.warning(f"Wikipedia API returned {resp.status_code}")
                    return []

                parser = _ListItemParser()
                parser.feed(resp.text)

            results = []
            for headline in parser.items:
                if _is_relevant(headline, query):
                    results.append(ResearchResult(
                        text=headline,
                        link="https://en.wikipedia.org/wiki/Portal:Current_events",
                        published=datetime.now(timezone.utc),
                        source="wikipedia",
                        weight=self.default_weight,
                    ))

            return results
        except Exception as e:
            logger.warning(f"Wikipedia search failed: {e}")
            return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wikipedia.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/research/wikipedia.py tests/test_wikipedia.py
git commit -m "feat: add Wikipedia Current Events text source"
```

---

## Chunk 3: Haiku Sentiment + Feature Integration + Wiring

### Task 9: Haiku Sentiment (Replace RoBERTa)

**Files:**
- Modify: `src/research/sentiment.py` (full rewrite)
- Modify: `tests/test_sentiment.py`

- [ ] **Step 1: Write the failing tests**

Replace contents of `tests/test_sentiment.py`:

```python
# tests/test_sentiment.py
import pytest
from unittest.mock import MagicMock, patch
from src.research.sentiment import SentimentAnalyzer


def test_positive_sentiment():
    analyzer = SentimentAnalyzer(use_llm=False)
    result = analyzer.analyze("This is absolutely amazing and wonderful!")
    assert result["label"] == "positive"
    assert result["score"] > 0.5


def test_negative_sentiment():
    analyzer = SentimentAnalyzer(use_llm=False)
    result = analyzer.analyze("This is terrible and awful, complete disaster.")
    assert result["label"] == "negative"
    assert result["score"] < -0.5


def test_batch_sentiment():
    analyzer = SentimentAnalyzer(use_llm=False)
    texts = ["Great news!", "Terrible outcome", "The weather is okay"]
    results = analyzer.analyze_batch(texts)
    assert len(results) == 3
    assert results[0]["label"] == "positive"
    assert results[1]["label"] == "negative"


@pytest.mark.asyncio
async def test_async_batch_vader_only():
    """Async batch falls back to VADER when use_llm=False."""
    analyzer = SentimentAnalyzer(use_llm=False)
    results = await analyzer.analyze_batch_async(
        ["Great news!", "Terrible outcome"],
        market_question="Will X happen?",
    )
    assert len(results) == 2
    assert results[0]["label"] == "positive"
    assert results[1]["label"] == "negative"


@pytest.mark.asyncio
async def test_async_batch_haiku_for_ambiguous():
    """Ambiguous texts (low VADER compound) get sent to Haiku."""
    analyzer = SentimentAnalyzer(use_llm=True, llm_threshold=0.4)

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = '[{"label":"positive","score":0.6}]'
    mock_client.messages.create.return_value = mock_response
    analyzer._anthropic = mock_client

    # "The meeting discussed results" is ambiguous for VADER
    results = await analyzer.analyze_batch_async(
        ["The meeting discussed results"],
        market_question="Will GDP grow?",
    )
    assert len(results) == 1
    # Haiku returned positive
    assert results[0]["label"] == "positive"
    assert results[0]["score"] == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_async_batch_haiku_fallback_on_error():
    """Falls back to VADER if Haiku fails."""
    analyzer = SentimentAnalyzer(use_llm=True, llm_threshold=0.4)

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API down")
    analyzer._anthropic = mock_client

    results = await analyzer.analyze_batch_async(
        ["The meeting discussed results"],
        market_question="Will GDP grow?",
    )
    assert len(results) == 1
    # Should still get a VADER result, not crash
    assert "label" in results[0]
    assert "score" in results[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sentiment.py -v`
Expected: FAIL — `SentimentAnalyzer` doesn't accept `use_llm` yet

- [ ] **Step 3: Rewrite sentiment.py**

**Note:** The spec says `analyze_batch` "becomes async". We implement this as a NEW method `analyze_batch_async()` while keeping the sync `analyze_batch()` as VADER-only for backward compat. Only `analyze_batch_async()` activates Haiku. The pipeline caller (`research/pipeline.py`) is updated to call `analyze_batch_async` in Task 12.

Replace `src/research/sentiment.py` with:

```python
# src/research/sentiment.py
import json
import logging
import re

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

DEFAULT_SENTIMENT_MODEL = "claude-haiku-4-5-20251001"


class SentimentAnalyzer:
    def __init__(
        self,
        use_llm: bool = False,
        llm_threshold: float = 0.4,
        sentiment_model: str = DEFAULT_SENTIMENT_MODEL,
        anthropic_client=None,
        # Legacy compat — ignored but accepted so existing callers don't break
        use_transformer: bool = False,
        ambiguity_threshold: float = 0.6,
    ):
        self.vader = SentimentIntensityAnalyzer()
        self.use_llm = use_llm
        self.llm_threshold = llm_threshold
        self.sentiment_model = sentiment_model
        self._anthropic = anthropic_client

    def _get_anthropic(self):
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic()
        return self._anthropic

    def _vader_analyze(self, text: str) -> dict:
        """Score a single text with VADER. Returns {label, score}."""
        compound = self.vader.polarity_scores(text)["compound"]
        label = "positive" if compound > 0.05 else ("negative" if compound < -0.05 else "neutral")
        return {"label": label, "score": compound}

    def analyze(self, text: str) -> dict:
        """Analyze sentiment of a single text with VADER. Returns {label, score}."""
        return self._vader_analyze(text)

    def analyze_batch(self, texts: list[str]) -> list[dict]:
        """Synchronous batch — VADER only. For Haiku support use analyze_batch_async."""
        return [self._vader_analyze(t) for t in texts]

    async def analyze_batch_async(
        self, texts: list[str], market_question: str | None = None,
    ) -> list[dict]:
        """Async batch with optional Haiku for ambiguous texts.

        Flow:
        1. VADER scores all texts
        2. Texts with abs(compound) < llm_threshold are "ambiguous"
        3. Ambiguous texts batched to Haiku (if use_llm=True and market_question given)
        4. Haiku results replace VADER for those texts
        5. On Haiku failure, VADER stands
        """
        vader_results = [self._vader_analyze(t) for t in texts]

        if not self.use_llm or not market_question:
            return vader_results

        # Find ambiguous indices
        ambiguous_indices = [
            i for i, r in enumerate(vader_results)
            if abs(r["score"]) < self.llm_threshold
        ]

        if not ambiguous_indices:
            return vader_results

        # Batch ambiguous texts to Haiku
        ambiguous_texts = [texts[i] for i in ambiguous_indices]
        haiku_results = await self._haiku_batch(ambiguous_texts, market_question)

        if haiku_results and len(haiku_results) == len(ambiguous_indices):
            for idx, haiku_result in zip(ambiguous_indices, haiku_results):
                vader_results[idx] = haiku_result

        return vader_results

    async def _haiku_batch(
        self, texts: list[str], market_question: str,
    ) -> list[dict] | None:
        """Send ambiguous texts to Haiku for sentiment scoring."""
        try:
            client = self._get_anthropic()
            numbered = "\n".join(f"{i+1}. {t[:500]}" for i, t in enumerate(texts))
            prompt = (
                f"Rate each text's sentiment toward this prediction market resolving YES.\n"
                f"Market: {market_question}\n"
                f"Texts:\n{numbered}\n"
                f'Return JSON array: [{{"label":"positive","score":0.7}}, ...]\n'
                f"Score: -1.0 (strongly suggests NO) to 1.0 (strongly suggests YES). "
                f"Label: positive if score > 0.05, negative if < -0.05, neutral otherwise.\n"
                f"Return ONLY valid JSON."
            )

            # Run sync Anthropic client in thread to avoid blocking event loop
            import asyncio
            response = await asyncio.to_thread(
                client.messages.create,
                model=self.sentiment_model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            try:
                results = json.loads(text)
            except json.JSONDecodeError:
                # Fallback: extract JSON array from response
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match:
                    results = json.loads(match.group())
                else:
                    logger.warning(f"Haiku returned non-JSON: {text[:200]}")
                    return None

            # Validate shape
            if not isinstance(results, list) or len(results) != len(texts):
                logger.warning(f"Haiku returned {len(results)} results for {len(texts)} texts")
                return None

            validated = []
            for r in results:
                score = float(r.get("score", 0))
                label = r.get("label", "neutral")
                if label not in ("positive", "negative", "neutral"):
                    label = "positive" if score > 0.05 else ("negative" if score < -0.05 else "neutral")
                validated.append({"label": label, "score": score})

            return validated
        except Exception as e:
            logger.warning(f"Haiku sentiment failed, falling back to VADER: {e}")
            return None

    def aggregate(self, results: list[dict]) -> dict:
        """Compute aggregate sentiment stats from a list of results."""
        if not results:
            return {"positive_ratio": 0, "negative_ratio": 0, "neutral_ratio": 0, "avg_score": 0, "sample_size": 0}

        pos = sum(1 for r in results if r["label"] == "positive")
        neg = sum(1 for r in results if r["label"] == "negative")
        total = len(results)
        avg_score = sum(r["score"] for r in results) / total

        return {
            "positive_ratio": pos / total,
            "negative_ratio": neg / total,
            "neutral_ratio": (total - pos - neg) / total,
            "avg_score": avg_score,
            "sample_size": total,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sentiment.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python -m pytest --tb=short -q`
Expected: All existing tests pass (sentiment.py has backward-compat params)

- [ ] **Step 6: Commit**

```bash
git add src/research/sentiment.py tests/test_sentiment.py
git commit -m "feat: replace RoBERTa with Haiku for ambiguous sentiment"
```

---

### Task 10: Config Additions

**Files:**
- Modify: `src/config.py:43-54,106-111`

- [ ] **Step 1: Add new settings to config.py**

After line 53 (`SOURCE_WEIGHT_GOOGLE_TRENDS`), add:

```python
    SOURCE_WEIGHT_METACULUS: float = 0.9
    SOURCE_WEIGHT_PREDICTIT: float = 0.85
    SOURCE_WEIGHT_WIKIPEDIA: float = 0.7

    # Sentiment LLM
    SENTIMENT_MODEL: str = "claude-haiku-4-5-20251001"
    SENTIMENT_USE_LLM: bool = True
    SENTIMENT_LLM_THRESHOLD: float = 0.4

    # FRED API
    FRED_API_KEY: str = ""
```

Add new source weights to the `weight_range` validator (line 106-111):

```python
    @field_validator(
        "SOURCE_WEIGHT_NEWSAPI", "SOURCE_WEIGHT_RSS_MAJOR",
        "SOURCE_WEIGHT_RSS_PREDICTION", "SOURCE_WEIGHT_RSS_GOOGLE",
        "SOURCE_WEIGHT_TWITTER", "SOURCE_WEIGHT_REDDIT",
        "SOURCE_WEIGHT_GOOGLE_TRENDS",
        "SOURCE_WEIGHT_METACULUS", "SOURCE_WEIGHT_PREDICTIT",
        "SOURCE_WEIGHT_WIKIPEDIA",
    )
```

- [ ] **Step 2: Run existing config tests**

Run: `python -m pytest tests/test_config_weights.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat: add config settings for new sources and Haiku sentiment"
```

---

### Task 11: Feature Integration (20 → 33 features)

**Files:**
- Modify: `src/predictor/features.py:5,29-55`
- Modify: `src/predictor/xgb_model.py:7-15`
- Modify: `src/predictor/trainer.py:69-91`
- Modify: `tests/test_predictor.py`

- [ ] **Step 1: Update extract_features to accept structured_data**

In `src/predictor/features.py`, change the function signature (line 5) and add 13 new features after line 54:

```python
def extract_features(market: ScannedMarket, sentiment_agg: dict, structured_data: dict | None = None) -> dict:
    """Extract features for XGBoost from market data, sentiment, and structured data."""
    # ... existing code unchanged through line 54 ...
    sd = structured_data or {}
    features = {
        # ... existing 20 features ...
        # CLOB features (5)
        "clob_bid_ask_spread": sd.get("clob_bid_ask_spread", 0.0),
        "clob_buy_depth": math.log1p(sd.get("clob_buy_depth", 0.0)),
        "clob_sell_depth": math.log1p(sd.get("clob_sell_depth", 0.0)),
        "clob_imbalance": sd.get("clob_imbalance", 0.5),
        "clob_midpoint_vs_gamma": sd.get("clob_midpoint_vs_gamma", 0.0),
        # CoinGecko features (4)
        "crypto_price_usd": math.log1p(sd.get("crypto_price_usd", 0.0)),
        "crypto_24h_change": sd.get("crypto_24h_change", 0.0),
        "crypto_market_cap": math.log1p(sd.get("crypto_market_cap", 0.0)),
        "crypto_is_relevant": sd.get("crypto_is_relevant", 0.0),
        # FRED features (4)
        "fred_cpi_latest": sd.get("fred_cpi_latest", 0.0),
        "fred_fed_funds_rate": sd.get("fred_fed_funds_rate", 0.0),
        "fred_unemployment": sd.get("fred_unemployment", 0.0),
        "fred_is_relevant": sd.get("fred_is_relevant", 0.0),
    }
    return features
```

- [ ] **Step 2: Update FEATURE_ORDER in xgb_model.py**

Replace `FEATURE_ORDER` (lines 7-15) with:

```python
FEATURE_ORDER = [
    "yes_price", "no_price", "spread", "log_liquidity", "log_volume_24h",
    "days_to_resolution", "volume_liquidity_ratio",
    "flag_wide_spread", "flag_high_volume", "flag_price_spike",
    "sentiment_positive_ratio", "sentiment_negative_ratio",
    "sentiment_neutral_ratio", "sentiment_avg_score", "sentiment_sample_size",
    "sentiment_polarity", "price_sentiment_gap",
    "sentiment_convergence", "narrative_alignment", "has_research_data",
    # CLOB order book (5)
    "clob_bid_ask_spread", "clob_buy_depth", "clob_sell_depth",
    "clob_imbalance", "clob_midpoint_vs_gamma",
    # CoinGecko crypto (4)
    "crypto_price_usd", "crypto_24h_change", "crypto_market_cap",
    "crypto_is_relevant",
    # FRED economic (4)
    "fred_cpi_latest", "fred_fed_funds_rate", "fred_unemployment",
    "fred_is_relevant",
]
```

- [ ] **Step 3: Update trainer.py feature defaults**

In `src/predictor/trainer.py`, add 13 new default features after line 90 (`"has_research_data": 0,`):

```python
            # Structured data defaults (no historical structured data available)
            "clob_bid_ask_spread": 0.0,
            "clob_buy_depth": 0.0,
            "clob_sell_depth": 0.0,
            "clob_imbalance": 0.5,
            "clob_midpoint_vs_gamma": 0.0,
            "crypto_price_usd": 0.0,
            "crypto_24h_change": 0.0,
            "crypto_market_cap": 0.0,
            "crypto_is_relevant": 0.0,
            "fred_cpi_latest": 0.0,
            "fred_fed_funds_rate": 0.0,
            "fred_unemployment": 0.0,
            "fred_is_relevant": 0.0,
```

- [ ] **Step 4: Update test_predictor.py feature count assertions**

In `tests/test_predictor.py`, there are TWO assertions to update:
1. Find `assert len(features) == 20` (in `test_extract_features`) → change to `== 33`
2. Find `assert len(result["features"]) == 20` (in `test_trainer_market_to_features_valid`) → change to `== 33`

Both must be updated since `extract_features` and `market_to_features` now produce 33 features.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_predictor.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/predictor/features.py src/predictor/xgb_model.py src/predictor/trainer.py tests/test_predictor.py
git commit -m "feat: expand features 20→33 with structured data support"
```

---

### Task 12: Wire Everything into Pipeline

**Files:**
- Modify: `src/research/pipeline.py:44,107`
- Modify: `src/pipeline.py:1-67,142-175,229-260`

- [ ] **Step 1: Register new text sources in ResearchPipeline**

In `src/research/pipeline.py`, change line 44 to use `analyze_batch_async`:

```python
# line 107: change from
sentiments = self.sentiment.analyze_batch(texts)
# to
sentiments = await self.sentiment.analyze_batch_async(texts, market_question=query)
```

- [ ] **Step 2: Wire new sources and structured pipeline in pipeline.py**

In `src/pipeline.py`, add imports after line 14:

```python
from src.research.metaculus import MetaculusSource
from src.research.predictit import PredictItSource
from src.research.wikipedia import WikipediaSource
from src.research.structured_pipeline import StructuredDataPipeline
from src.research.clob import CLOBSource
from src.research.coingecko import CoinGeckoSource
from src.research.fred import FREDSource
```

In `__init__` (after line 63, GoogleTrendsSource), add new text sources:

```python
                MetaculusSource(weight=self.settings.SOURCE_WEIGHT_METACULUS),
                PredictItSource(weight=self.settings.SOURCE_WEIGHT_PREDICTIT),
                WikipediaSource(weight=self.settings.SOURCE_WEIGHT_WIKIPEDIA),
```

After the `research_pipeline` init (after line 67), add structured pipeline:

```python
        self.structured_pipeline = StructuredDataPipeline(
            sources=[
                CLOBSource(),
                CoinGeckoSource(),
                FREDSource(api_key=self.settings.FRED_API_KEY),
            ],
            timeout=self.settings.RESEARCH_TIMEOUT,
        )
```

Update `SentimentAnalyzer` init (lines 35-38) to pass LLM settings:

```python
        self.sentiment = SentimentAnalyzer(
            use_llm=self.settings.SENTIMENT_USE_LLM,
            llm_threshold=self.settings.SENTIMENT_LLM_THRESHOLD,
            sentiment_model=self.settings.SENTIMENT_MODEL,
        )
```

- [ ] **Step 3: Add parallel structured data fetch in run_cycle**

In `run_cycle` (around line 258-260), add structured pipeline parallel to research:

```python
        # Parallelize BOTH tracks — research and structured data run concurrently
        self._set_activity("researching", f"Researching {len(targets)} markets in parallel")
        research_tasks = [self.research(m) for m in targets]
        structured_tasks = [self.structured_pipeline.fetch(m) for m in targets]
        all_results = await asyncio.gather(
            asyncio.gather(*research_tasks, return_exceptions=True),
            asyncio.gather(*structured_tasks, return_exceptions=True),
        )
        research_results, structured_results = all_results
```

- [ ] **Step 4: Pass structured_data to predict**

Update `predict()` signature (line 142) to accept structured data:

```python
    async def predict(self, market: ScannedMarket, research: ResearchReport, structured_data: dict | None = None):
```

Update the `extract_features` call (line 174):

```python
        features = extract_features(market, sentiment_agg, structured_data=structured_data)
```

In `run_cycle`, pass structured result to predict (around line 271):

```python
                # Get structured data for this market
                struct_data = structured_results[i]
                if isinstance(struct_data, Exception):
                    logger.warning(f"Structured data failed for {market.question[:50]}: {struct_data}")
                    struct_data = None

                self._set_activity("predicting", f"[{i+1}/{len(targets)}] {market.question}")
                prediction = await self.predict(market, research, structured_data=struct_data)
```

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/research/pipeline.py src/pipeline.py
git commit -m "feat: wire two-track data pipeline with parallel execution"
```

---

### Task 13: Final Integration Test

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Add integration test for structured pipeline in the main pipeline**

Add to `tests/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_includes_structured_sources():
    """Verify pipeline initializes with structured pipeline."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        settings = Settings()
        settings.SENTIMENT_USE_LLM = False  # disable for test
        pipe = Pipeline(settings=settings, db_path=":memory:")
        assert hasattr(pipe, "structured_pipeline")
        assert len(pipe.structured_pipeline.sources) == 3  # CLOB, CoinGecko, FRED
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite one final time**

Run: `python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test: add integration test for two-track pipeline"
```
