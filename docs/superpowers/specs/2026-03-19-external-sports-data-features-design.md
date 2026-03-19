# External Sports Data Features

**Date:** 2026-03-19
**Status:** Approved

## Problem

The XGBoost model lacks external sports data features that the lesson consolidation system has repeatedly identified as high-priority: rest days between games, franchise quality differential, and closing line value from sharp bookmakers. These features are currently unavailable because the pipeline has no sports schedule, standings, or odds data sources.

## Solution

Add two new structured data sources following the existing `StructuredDataSource` ABC pattern, a shared team extraction utility, and 4 new XGBoost features (+ 1 diagnostic feature stored for future training).

## Shared Component: TeamExtractor

**`src/research/team_extractor.py`**

A utility class shared by both data sources. Extracts sport and team info from market questions using Haiku LLM, with in-memory caching so each question is only parsed once.

```python
class TeamExtractor:
    async def extract(question: str) -> TeamInfo | None
```

Returns:
```json
{"sport": "nba", "team_a": "Toronto Raptors", "team_b": "Chicago Bulls"}
```

- `team_a` = the team whose outcome corresponds to YES on the market (first-mentioned or favorite side)
- `team_b` = the opposing team
- Returns `None` for non-sports markets (crypto, politics, social, esports)
- Caches by question string — both sources call `extract()` but only the first triggers the LLM

**Team ID resolution:** On first use per sport, fetches team list from BALLDONTLIE `/teams` endpoint and caches in memory. LLM-normalized team names are fuzzy-matched against the cached list (no static dict to maintain).

## Data Sources

### 1. `SportsDataSource` (`src/research/sports_data.py`)

Fetches schedule and standings data from the BALLDONTLIE API (free tier, covers NBA, NHL, NFL, MLB).

**Flow:**
1. Call `TeamExtractor.extract(question)` — gets sport + teams (cached if already called)
2. Look up BALLDONTLIE team IDs via dynamic team cache
3. Fetch recent games for both teams → compute days since last game → `rest_days_differential`
4. Fetch current standings for both teams → compute win-pct percentile rank delta → `standings_pct_delta`

**BALLDONTLIE endpoints used:**
- `GET /v1/{sport}/teams` — fetch and cache team list (once per sport per session)
- `GET /v1/{sport}/games?team_ids[]={id}&start_date={}&end_date={}` — recent games
- `GET /v1/{sport}/standings` — current season standings

**Returns:**
```python
{
    "rest_days_differential": 2.0,    # team_a rest - team_b rest (float)
    "standings_pct_delta": 0.35,      # team_a win_pct - team_b win_pct (-1 to 1)
    "sports_is_relevant": 1.0,        # 1.0 if sports data found, 0.0 otherwise
}
```

### 2. `OddsDataSource` (`src/research/odds_data.py`)

Fetches pre-game odds from OddsPapi (free tier, 250 req/month, aggregates Pinnacle + 350 books).

**Flow:**
1. Call `TeamExtractor.extract(question)` — cache hit if SportsDataSource already called it
2. If no teams found or monthly request budget exhausted, return empty
3. Fetch current odds for the matchup from OddsPapi
4. Extract Pinnacle (or sharpest available) moneyline odds → convert to implied probability
5. Return `sharp_implied_prob` for CLV calculation

**Rate limit budget:**
- Track monthly request count in DB (`odds_api_requests` counter)
- Pipeline runs once/day, ~5-10 sports markets per run = ~150-300 requests/month
- Proactively skip when count > 220 (leave buffer)

**Returns:**
```python
{
    "sharp_implied_prob": 0.62,  # Pinnacle-implied probability for team_a/YES side
}
```

### 3. Feature Extraction (`src/predictor/features.py`)

**XGBoost input features (added to FEATURE_ORDER):**

| Feature | Type | Source | Default |
|---|---|---|---|
| `rest_days_differential` | float | BALLDONTLIE schedule | 0.0 |
| `standings_pct_delta` | float (-1 to 1) | BALLDONTLIE standings | 0.0 |
| `sports_is_relevant` | float (0/1) | Team extraction success | 0.0 |

**Diagnostic feature (stored in features_json but NOT in FEATURE_ORDER):**

| Feature | Type | Computation | Default |
|---|---|---|---|
| `closing_line_value_delta` | float | model_prob - sharp_implied_prob | 0.0 |

CLV delta is computed in `pipeline.py` after calibration (needs predicted probability). It is saved in `features_json` for future training data but is NOT an XGBoost input during inference — this avoids the circular dependency of using the model's output as its own input. Future model versions can train on it once enough labeled data accumulates.

## Architecture

```
pipeline.py
  └── StructuredDataPipeline
        ├── CLOBSource (existing)
        ├── CoinGeckoSource (existing)
        ├── FREDSource (existing)
        ├── SportsDataSource (new)  ← BALLDONTLIE + TeamExtractor
        └── OddsDataSource (new)   ← OddsPapi + TeamExtractor (cache hit)

TeamExtractor (shared singleton)
  ├── LLM extraction (Haiku, cached by question)
  └── BALLDONTLIE team list (cached by sport)
```

Both new sources implement `StructuredDataSource` ABC with `async def fetch(market) -> dict`.

The `TeamExtractor` instance is created once in `pipeline.py` and passed to both sources via constructor injection.

## Graceful Degradation

- Non-sports markets: TeamExtractor returns None, sources return empty dict, features default to 0.0, `sports_is_relevant` = 0.0
- API errors / rate limits: log warning, return empty dict, don't block the pipeline
- Sport not covered by BALLDONTLIE: return empty dict
- Team not found via fuzzy match: log warning, return empty dict
- OddsPapi monthly budget exhausted: skip CLV, log warning
- Missing API keys: sources report `is_available = False`, pipeline skips them

## Config

```env
BALLDONTLIE_API_KEY=     # free tier key from balldontlie.io
ODDSPAPI_API_KEY=        # free tier key from oddspapi.io
```

Both optional. Sources return empty dict if key is not set.

## Files to Create/Modify

**Create:**
- `src/research/team_extractor.py` — shared TeamExtractor class
- `src/research/sports_data.py` — SportsDataSource class
- `src/research/odds_data.py` — OddsDataSource class
- `tests/test_sports_data.py` — tests for SportsDataSource
- `tests/test_odds_data.py` — tests for OddsDataSource
- `tests/test_team_extractor.py` — tests for TeamExtractor

**Modify:**
- `src/predictor/features.py` — add 3 XGBoost features from structured_data
- `src/predictor/xgb_model.py` — add 3 features to FEATURE_ORDER
- `src/predictor/trainer.py` — add defaults for Gamma API fallback
- `src/pipeline.py` — create TeamExtractor, pass to both sources, add sources to StructuredDataPipeline, compute CLV delta post-calibration and store in features_json
- `src/config.py` — add BALLDONTLIE_API_KEY and ODDSPAPI_API_KEY settings
- `tests/test_predictor.py` — update feature count assertion (37 → 40)

## Deployment

After deploying this change:
1. Retrain the model: `python3 run.py --train` (required — feature count changes from 37 to 40)
2. Add API keys to `.env` on the droplet
3. Old predictions without new features will default to 0.0 during training (handled by `features.get(f, 0.0)`)

## Testing

- Mock BALLDONTLIE and OddsPapi responses in tests
- Verify TeamExtractor caches correctly (one LLM call per question, not per source)
- Verify graceful degradation when APIs are unavailable or keys missing
- Verify non-sports markets return default values with `sports_is_relevant = 0.0`
- Verify CLV delta stored in features_json but NOT used in XGBoost inference
- Verify feature extraction produces correct values from structured_data
