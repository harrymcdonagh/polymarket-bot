# Expanded Research Sources — Design Spec

## Goal

Add NewsAPI, Twitter (twscrape), and expanded RSS feeds as weighted research sources for the Polymarket bot's sentiment analysis pipeline. Sources conform to a common interface, are independently testable, and degrade gracefully when unconfigured.

## Architecture

Source Adapter Pattern: each research source implements a `ResearchSource` ABC. A `ResearchPipeline` orchestrator fans out queries to all available sources, deduplicates results, runs sentiment analysis with source-level trust weights, and returns a weighted aggregate.

## Section 1: Source Interface & Results

### ResearchResult

Dataclass representing a single research result:

| Field      | Type  | Description                              |
|------------|-------|------------------------------------------|
| text       | str   | Title + truncated description (max 500c) |
| link       | str   | URL to original article/tweet            |
| published  | datetime or None | Parsed publication date (via `_parse_published()` utility in base.py) |
| source     | str   | Source identifier (e.g. "newsapi", "rss_reuters", "twitter") |
| weight     | float | Source-level trust weight (0.0–1.0)      |

### ResearchSource ABC

Located in `src/research/base.py`:

```python
class ResearchSource(ABC):
    name: str               # identifier used in results
    default_weight: float   # trust weight

    @abstractmethod
    async def search(self, query: str) -> list[ResearchResult]:
        """Search this source for the given query."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this source is configured and usable."""
```

### Existing Source Adapters

`RSSResearcher`, `TwitterResearcher`, and `RedditResearcher` get thin adapter wrappers conforming to `ResearchSource`. Internal logic stays unchanged.

## Section 2: New & Expanded Sources

### NewsAPI (`src/research/newsapi.py`)

- Package: `newsapi-python`
- Endpoint: `/v2/top-headlines` (free tier only supports this, not `/v2/everything`)
- Query via `q` parameter (searches within headline text), no `country` filter to maximize coverage
- Free tier: 100 requests/day, max 100 results per request
- Cache: per-query, 15-minute TTL (dict with timestamps) to stay well under rate limit
- Default weight: **1.0**
- Env var: `NEWSAPI_KEY` (empty string = disabled)
- Returns: title + description as text, article URL, publishedAt
- Limitation: free tier headlines may not always match niche prediction market queries — this is expected, the source adds value for high-profile topics

### Twitter / twscrape (`src/research/twitter.py` — extend existing)

- Already uses twscrape for tweet search
- Add `is_available()` — checks if twscrape account pool has logged-in accounts
- Default weight: **0.5**
- No env vars needed (twscrape manages its own `accounts.db`)

### Expanded RSS (`src/research/rss.py` — extend existing)

Add a feed registry with per-feed metadata. All URLs verified as working:

**Query feeds** (support `{query}` substitution):

| Feed           | URL                                                              | Weight | Source Tag    |
|----------------|------------------------------------------------------------------|--------|---------------|
| Google News    | `https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en` | 0.7 | rss_google |

**Static feeds** (fetched in full, filtered for relevance by fuzzy-matching titles against the query):

| Feed           | URL                                                              | Weight | Source Tag    |
|----------------|------------------------------------------------------------------|--------|---------------|
| BBC News       | `https://feeds.bbci.co.uk/news/rss.xml`                         | 0.9    | rss_bbc       |
| Al Jazeera     | `https://www.aljazeera.com/xml/rss/all.xml`                     | 0.9    | rss_aljazeera |
| NPR            | `https://feeds.npr.org/1001/rss.xml`                            | 0.9    | rss_npr       |
| The Hill       | `https://thehill.com/news/feed/`                                 | 0.9    | rss_thehill   |
| Polymarket Blog| `https://news.polymarket.com/feed`                              | 0.8    | rss_polymarket|
| Manifold Blog  | `https://news.manifold.markets/feed`                            | 0.8    | rss_manifold  |

**Removed:** Reuters (discontinued RSS in 2020), AP News (no official RSS), Metaculus (no public RSS, API only — could be added as a separate source later).

- Each feed result carries its specific source tag
- Results inherit the feed's configured weight
- Static feeds are cached with 15-minute TTL (they don't change per-query)
- Relevance filtering on static feeds: fuzzy match title against query with 0.4 threshold (lower than dedup since we're matching topic, not exact article). This threshold is tunable and should be validated empirically

## Section 3: Integration with Existing Pipeline

### Current State

`src/pipeline.py` has a `Pipeline.research()` method (lines 73-122) that:
1. Fans out to `_search_twitter()`, `_search_reddit()`, `_rss.search()` via `asyncio.gather`
2. Runs `SentimentAnalyzer.analyze_batch()` per source
3. Builds `SentimentResult` objects per source
4. Returns a `ResearchReport` with `sentiments: list[SentimentResult]`

The `ResearchReport` feeds into `Pipeline.predict()` which averages sentiment across sources and passes to feature extraction.

### Refactoring Plan

`Pipeline.research()` will be refactored to delegate to `ResearchPipeline`:

1. `ResearchPipeline.search(query)` replaces the manual fan-out in `Pipeline.research()`
2. `ResearchPipeline` returns a `WeightedSentimentResult` (see below) which includes per-source `SentimentResult` objects — these map directly to the existing `SentimentResult` model
3. `Pipeline.research()` constructs `ResearchReport` from the pipeline's output, preserving the existing interface consumed by `predict()`
4. The `source_breakdown` from `WeightedSentimentResult` is stored alongside the report for dashboard display
5. `Pipeline.__init__` creates a `ResearchPipeline` instance instead of individual `_twitter`, `_reddit`, `_rss` attributes
6. `Pipeline._search_twitter()`, `Pipeline._search_reddit()` private methods are removed — that logic moves into the source adapters

### Backward Compatibility

- `ResearchReport` and `SentimentResult` models are unchanged
- `Pipeline.predict()` is unchanged — it still receives a `ResearchReport`
- Feature extraction is unchanged
- The only breaking change is internal to `Pipeline.research()`

### ResearchPipeline (`src/research/pipeline.py`)

Orchestration flow:

```
query
  → fan out to all sources where is_available() == True (asyncio.gather)
  → collect ResearchResult lists
  → deduplicate by fuzzy title match (~85% similarity threshold)
  → pass texts to SentimentAnalyzer.analyze_batch()
  → multiply each sentiment score by result's source weight
  → compute weighted aggregate
  → return WeightedSentimentResult
```

### Deduplication

Same story often appears across multiple sources (BBC RSS + Google News + NewsAPI). Fuzzy matching on the `text` field (title portion) using `difflib.SequenceMatcher` with 0.85 ratio threshold. When duplicates found, keep the result with the highest source weight.

### Timeouts

Each source gets a 10-second timeout via `asyncio.wait_for()`. If a source is slow or down, the pipeline continues with whatever sources responded. Timeout logged as warning.

### WeightedSentimentResult

```python
{
    "positive_ratio": float,    # weighted
    "negative_ratio": float,    # weighted
    "neutral_ratio": float,     # weighted
    "weighted_avg_score": float, # sum(score * weight) / sum(weight)
    "sample_size": int,
    "source_breakdown": {
        "newsapi": {"count": 5, "avg_score": 0.72},
        "rss_reuters": {"count": 3, "avg_score": 0.65},
        "twitter": {"count": 12, "avg_score": 0.41},
        ...
    }
}
```

## Section 4: Configuration & Graceful Degradation



### New Settings Fields (`src/config.py`)

| Field                      | Type  | Default | Description                    |
|----------------------------|-------|---------|--------------------------------|
| NEWSAPI_KEY                | str   | ""      | Empty = source disabled        |
| SOURCE_WEIGHT_NEWSAPI      | float | 1.0     | NewsAPI trust weight           |
| SOURCE_WEIGHT_RSS_MAJOR    | float | 0.9     | BBC, Al Jazeera, NPR, The Hill |
| SOURCE_WEIGHT_RSS_PREDICTION | float | 0.8   | Polymarket, Manifold           |
| SOURCE_WEIGHT_RSS_GOOGLE   | float | 0.7     | Google News aggregator         |
| SOURCE_WEIGHT_TWITTER      | float | 0.5     | Twitter/twscrape               |
| SOURCE_WEIGHT_REDDIT       | float | 0.6     | Reddit (when available)        |
| RESEARCH_TIMEOUT           | int   | 10      | Per-source timeout in seconds  |

All weights validated: `0.0 < weight <= 1.0`.

### Graceful Degradation Rules

| Condition                    | Behavior                                      |
|------------------------------|-----------------------------------------------|
| No NEWSAPI_KEY               | Skip NewsAPI, log info once at startup         |
| No twscrape accounts         | Skip Twitter, log info once at startup         |
| No Reddit credentials        | Skip Reddit, log info once at startup          |
| Source times out              | Log warning, continue with other sources       |
| Source raises exception       | Log warning, continue with other sources       |
| All sources fail              | Return empty results with warning, don't crash |
| No API keys at all            | Still works — Google News RSS needs no auth    |

### Dashboard Integration

- Source weights editable in the settings panel (both terminal and web)
- Source breakdown visible in web dashboard (which sources contributed to a market's analysis)

## Tech Stack

- `newsapi-python` — NewsAPI client
- `twscrape` — already installed, Twitter scraping
- `feedparser` — already installed, RSS parsing
- `difflib` — stdlib, fuzzy deduplication
- `asyncio` — async fan-out for parallel source queries

## File Map

| File                          | Action | Purpose                        |
|-------------------------------|--------|--------------------------------|
| `src/research/base.py`        | Create | ABC + ResearchResult dataclass |
| `src/research/newsapi.py`     | Create | NewsAPI source                 |
| `src/research/rss.py`         | Modify | Add feed registry, weights, adapter |
| `src/research/twitter.py`     | Modify | Add is_available(), adapter    |
| `src/research/reddit.py`      | Modify | Add is_available(), adapter    |
| `src/research/pipeline.py`    | Create | Orchestrator + weighted aggregation |
| `src/research/sentiment.py`   | No change | Used by pipeline as-is      |
| `src/pipeline.py`             | Modify | Refactor research() to delegate to ResearchPipeline |
| `src/config.py`               | Modify | Add new settings fields        |
| `src/dashboard/service.py`    | Modify | Expose source breakdown        |
| `src/dashboard/web.py`        | Modify | Source breakdown endpoint       |
| `src/dashboard/templates/index.html` | Modify | Display source breakdown |
| `tests/test_research_base.py` | Create | Interface + result tests       |
| `tests/test_newsapi.py`       | Create | NewsAPI source tests           |
| `tests/test_pipeline.py`      | Create | Pipeline orchestration tests   |
| `tests/test_rss.py`           | Modify | Expanded RSS tests             |
