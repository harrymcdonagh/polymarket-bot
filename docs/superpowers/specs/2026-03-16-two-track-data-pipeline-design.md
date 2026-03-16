# Two-Track Data Pipeline: Free Data Sources + Haiku Sentiment

## Problem

The bot's prediction accuracy is limited by narrow data coverage. It relies on 5 text-based research sources (NewsAPI, RSS, Twitter, Reddit, Google Trends) with VADER sentiment analysis. Several high-value free data sources are untapped, and VADER misclassifies nuanced prediction-market language.

## Solution

Add 6 free data sources and replace VADER with Haiku for ambiguous sentiment. Data is split into two tracks:

- **Track 1 (Text):** Existing sources + 3 new text sources, analyzed with Haiku sentiment (VADER fallback)
- **Track 2 (Structured):** 3 new numeric data sources that feed directly into XGBoost features, skipping sentiment

Both tracks run in parallel and merge at the feature extraction step.

## Architecture

```
Market Question
    ├── Track 1: Text Research
    │   ├── NewsAPI, RSS, Twitter, Reddit, Google Trends (existing)
    │   ├── Metaculus community forecasts (NEW)
    │   ├── PredictIt market prices (NEW)
    │   ├── Wikipedia Current Events (NEW)
    │   └── Haiku sentiment for ambiguous texts (REPLACES VADER)
    │   → sentiment_agg dict
    │
    ├── Track 2: Structured Data
    │   ├── Polymarket CLOB order book (NEW)
    │   ├── CoinGecko crypto prices (NEW)
    │   ├── FRED economic indicators (NEW)
    │   → structured_features dict
    │
    └── extract_features(market, sentiment_agg, structured_data)
        → 33 features (up from 20) → XGBoost + Calibrator
```

## Track 1: New Text Sources

### Metaculus (`src/research/metaculus.py`)

A `ResearchSource` adapter that queries the free Metaculus API for community forecasts from calibrated superforecasters.

- **API:** `GET https://www.metaculus.com/api/questions/?search={query}&status=open&type=forecast` (v2 API, no auth needed)
- **Output:** Synthetic text like "Metaculus community predicts 73% likelihood (847 forecasters)"
- **Weight:** 0.9 (high — calibrated forecasters)
- **Availability:** Always (no key needed)
- **Fallback:** Returns empty list on API error

### PredictIt (`src/research/predictit.py`)

A `ResearchSource` adapter that fetches PredictIt market prices and fuzzy-matches them to the Polymarket question.

- **API:** `GET https://www.predictit.org/api/marketdata/all/`
- **Output:** Synthetic text like "PredictIt prices this at 62% YES (market: 'Will X happen?')"
- **Weight:** 0.85 (another prediction market's price is strong signal)
- **Availability:** Always (no key needed)
- **Matching:** Compare PredictIt market names against Polymarket question using `SequenceMatcher`. Threshold: 0.5 similarity. Return top 3 matches.
- **Note:** PredictIt covers US politics heavily but not crypto. Source naturally activates for political markets.
- **Risk:** PredictIt shut down markets in 2023 after losing its CFTC no-action letter. The API may return stale or empty data. Implementation must handle empty/error responses gracefully. If the API is confirmed dead at implementation time, substitute with Manifold Markets API (`GET https://api.manifold.markets/v0/search-markets?term={query}`) which has the same structure (free, no auth, returns market probabilities).

### Wikipedia Current Events (`src/research/wikipedia.py`)

A `ResearchSource` adapter that fetches today's current events from Wikipedia.

- **API:** `GET https://en.wikipedia.org/api/rest_v1/page/html/Portal%3ACurrent_events` — returns HTML of today's events. Parse with `html.parser` to extract list items. Each `<li>` is one event headline.
- **Output:** Matching headlines as ResearchResults
- **Weight:** 0.7 (factual but not predictive)
- **Availability:** Always (no key needed)
- **Filtering:** Same relevance check as RSS static feeds (`_is_relevant()` from rss.py)

### All three sources:
- Follow the existing `ResearchSource` ABC
- Added to the `ResearchPipeline` sources list in `src/research/pipeline.py`
- Run in parallel with existing sources via `asyncio.gather`
- Gracefully disabled on error (return empty list)

## Track 2: Structured Data Sources

### New ABC (`src/research/structured_base.py`)

```python
class StructuredDataSource(ABC):
    name: str

    @abstractmethod
    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        """Return numeric features. Empty dict if unavailable."""

    @abstractmethod
    def is_available(self) -> bool: ...
```

Key difference from `ResearchSource`: takes full `ScannedMarket` (not just query string), returns named floats instead of text.

### Polymarket CLOB Order Book (`src/research/clob.py`)

Fetches real-time order book depth from the public CLOB REST API.

- **API:** `GET https://clob.polymarket.com/book?token_id={token_yes_id}`
- **No authentication needed** for read-only order book data
- **Features returned:**
  - `clob_bid_ask_spread` — tightest spread on the order book
  - `clob_buy_depth` — total $ within 5% of midpoint on buy side
  - `clob_sell_depth` — total $ within 5% of midpoint on sell side
  - `clob_imbalance` — `buy_depth / (buy_depth + sell_depth)`, >0.5 = bullish pressure
  - `clob_midpoint_vs_gamma` — difference between CLOB midpoint and Gamma API price (detects stale prices)
- **Availability:** Always (public endpoint)
- **Requires:** `ScannedMarket.token_yes_id` field — verify this is available from scanner

### CoinGecko Crypto Prices (`src/research/coingecko.py`)

Fetches current crypto prices and 24h changes. Only activates for crypto-related markets.

- **API:** `GET https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true`
- **Activation:** Keyword detection in market question: bitcoin, BTC, ethereum, ETH, solana, SOL, crypto, etc. Maps keywords to CoinGecko IDs.
- **Features returned:**
  - `crypto_price_usd` — current price (0 if not crypto market)
  - `crypto_24h_change` — percentage change (0 if not crypto)
  - `crypto_market_cap` — market cap in USD from `/simple/price?include_market_cap=true` (0 if not crypto). Log-transformed in features.py.
  - `crypto_is_relevant` — 1.0 if crypto market, 0.0 otherwise
- **Rate limit:** 30 calls/min free tier. In-memory cache with 5-minute TTL (dict of `{coin_id: (timestamp, data)}`).
- **Availability:** Always (no key needed)

### FRED Economic Indicators (`src/research/fred.py`)

Fetches key economic indicators. Only activates for economic/political markets.

- **Data source:** FRED API requires a free API key (register at https://fred.stlouisfed.org/docs/api/api_key.html). Add `FRED_API_KEY` to config.
- **API:** `GET https://api.stlouisfed.org/fred/series/observations?series_id={ID}&api_key={KEY}&file_type=json&sort_order=desc&limit=1`
- **Series fetched:**
  - `CPIAUCSL` — Consumer Price Index (inflation)
  - `FEDFUNDS` — Federal Funds Rate
  - `UNRATE` — Unemployment Rate
- **Activation:** Keyword detection: inflation, CPI, interest rate, Fed, unemployment, recession, GDP, economy, etc.
- **Features returned (4):**
  - `fred_cpi_latest` — latest CPI reading (0 if not economic market)
  - `fred_fed_funds_rate` — current rate (0 if not economic)
  - `fred_unemployment` — latest rate (0 if not economic)
  - `fred_is_relevant` — 1.0 if economic market, 0.0 otherwise
- **Caching:** In-memory dict with 6-hour TTL (economic data updates monthly/quarterly, not per-cycle)
- **Availability:** True if `FRED_API_KEY` is set and initial fetch succeeds. Gracefully disabled otherwise.

### Orchestration (`src/research/structured_pipeline.py`)

```python
class StructuredDataPipeline:
    def __init__(self, sources: list[StructuredDataSource], timeout: float = 10.0):
        self.sources = sources
        self.timeout = timeout

    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        """Run all sources in parallel, merge feature dicts."""
```

- Runs all sources via `asyncio.gather` with per-source timeout
- Merges dicts (no key collisions since each source uses its own prefix)
- Failed sources return empty dict, features default to 0.0

## Haiku Sentiment

### Changes to `src/research/sentiment.py`

**Flow:**
1. VADER scores all texts (fast, free)
2. Texts where `abs(compound) < SENTIMENT_LLM_THRESHOLD` are "ambiguous" — i.e., VADER's confidence is low (compound close to 0). This is the OPPOSITE of the existing RoBERTa trigger (which fires when `abs(compound) > ambiguity_threshold`). The LLM threshold replaces the RoBERTa path entirely.
3. Ambiguous texts are batched (10-15 per call) and sent to Haiku
4. Haiku returns JSON: `[{"label": "positive|negative|neutral", "score": -1.0 to 1.0}, ...]`
5. Haiku results replace VADER results for those texts
6. If Haiku fails or returns malformed JSON, VADER result stands (fallback). Use `re.search(r'\[.*\]', text, re.DOTALL)` JSON extraction as fallback parser, same pattern as calibrator.py.

**Score semantics:** Both VADER and Haiku return scores on the same scale: -1.0 (negative/bearish) to +1.0 (positive/bullish). The `label` field maps: score > 0.05 = "positive", score < -0.05 = "negative", else "neutral". This matches the existing VADER output shape exactly — downstream consumers (`research/pipeline.py`, `features.py`) are unchanged.

**Haiku prompt (kept minimal for speed/cost):**
```
Rate each text's sentiment toward this prediction market resolving YES.
Market: {question}
Texts:
1. {text1}
2. {text2}
...
Return JSON array: [{"label":"positive","score":0.7}, ...]
Score: -1.0 (strongly suggests NO) to 1.0 (strongly suggests YES). Label: positive if score > 0.05, negative if < -0.05, neutral otherwise.
Return ONLY valid JSON.
```

**Key change:** `analyze_batch()` becomes `async def analyze_batch()` and accepts an optional `market_question: str` parameter so Haiku can contextualize sentiment relative to the market. When `market_question` is None, falls back to pure VADER (no LLM calls). Return type remains `list[dict]` with the same `{"label": str, "score": float}` shape. Constructor gains `anthropic_client` and `settings` parameters for Haiku access (same pattern as `PostmortemAnalyzer`).

**Caller change:** `ResearchPipeline.search_and_analyze(query)` in `src/research/pipeline.py` changes its call from `self.sentiment.analyze_batch(texts)` to `await self.sentiment.analyze_batch(texts, market_question=query)`. Since `query` is already `market.question` (set in `src/pipeline.py`), no signature change to `search_and_analyze` is needed.

**RoBERTa removal:** The `use_transformer` code path and `transformers` dependency are removed entirely. Remove `transformers` and `torch` from `requirements.txt` if no other module uses them.

**Config additions:**
- `SENTIMENT_MODEL: str = "claude-haiku-4-5-20251001"` (separate from NARRATIVE_MODEL — allows independent tuning)
- `SENTIMENT_USE_LLM: bool = True`
- `SENTIMENT_LLM_THRESHOLD: float = 0.4` — texts where `abs(vader_compound) < 0.4` are sent to Haiku

**Cost estimate:** Assuming 30-40% of articles are ambiguous (abs compound < 0.4), ~15-20 articles per market, 20 markets per cycle, cycles every 5 minutes: ~$40-50/month.

## Feature Integration

### Changes to `src/predictor/features.py`

```python
def extract_features(market, sentiment_agg, structured_data=None):
    sd = structured_data or {}
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
```

Log-transform applied to depth and price values (large magnitudes).

### Changes to `src/predictor/xgb_model.py`

FEATURE_ORDER grows from 20 to 33. Existing models still work — `_features_to_array()` uses `.get(f, 0.0)` for missing keys.

### Changes to `src/predictor/trainer.py`

Gamma API fallback template gains 13 new features all defaulted to 0.

### Changes to `src/pipeline.py`

```python
# In __init__:
self.structured_pipeline = StructuredDataPipeline(
    sources=[
        CLOBSource(),
        CoinGeckoSource(),
        FREDSource(),
    ],
    timeout=self.settings.RESEARCH_TIMEOUT,
)

# In run_cycle, both tracks run in parallel:
research_tasks = [self.research(m) for m in targets]
structured_tasks = [self.structured_pipeline.fetch(m) for m in targets]
research_results = await asyncio.gather(*research_tasks, return_exceptions=True)
structured_results = await asyncio.gather(*structured_tasks, return_exceptions=True)

# In predict:
features = extract_features(market, sentiment_agg, structured_data=structured)
```

## Config Additions (`src/config.py`)

```python
# Sentiment LLM
SENTIMENT_MODEL: str = "claude-haiku-4-5-20251001"
SENTIMENT_USE_LLM: bool = True
SENTIMENT_LLM_THRESHOLD: float = 0.4

# FRED API
FRED_API_KEY: str = ""

# Source weights for new text sources
SOURCE_WEIGHT_METACULUS: float = 0.9
SOURCE_WEIGHT_PREDICTIT: float = 0.85
SOURCE_WEIGHT_WIKIPEDIA: float = 0.7
```

Add the three new source weight fields to the existing `weight_range` `@field_validator` list in config.py.

## Files Changed

**New files (8):**
- `src/research/metaculus.py`
- `src/research/predictit.py`
- `src/research/wikipedia.py`
- `src/research/structured_base.py`
- `src/research/structured_pipeline.py`
- `src/research/clob.py`
- `src/research/coingecko.py`
- `src/research/fred.py`

**Modified files (7):**
- `src/research/sentiment.py` — Haiku for ambiguous, VADER fallback, async analyze_batch
- `src/research/pipeline.py` — register 3 new text sources, pass market_question to analyze_batch
- `src/predictor/features.py` — structured_data param, 13 new features
- `src/predictor/xgb_model.py` — FEATURE_ORDER 20→33
- `src/predictor/trainer.py` — new feature defaults
- `src/pipeline.py` — wire up structured pipeline, parallel track execution
- `src/config.py` — new settings (sentiment LLM, FRED key, source weights)

## Out of Scope

- Auto-retrain XGBoost on accumulated trades
- Calibration curve tracking
- Formal market category classification system
- Decision trace logging
- Order book time-series storage
- Source-level accuracy tracking

These are planned for subsequent improvement cycles.

## Testing

Each new source gets:
- Unit test with mocked API response
- Test for graceful failure (API down → empty result)
- Test for `is_available()` behavior

Integration:
- Test `extract_features()` with and without structured_data
- Test FEATURE_ORDER length matches feature dict output
- Test Haiku sentiment fallback to VADER
- Test full pipeline with mocked sources
