# Polymarket Prediction Bot

An autonomous prediction market trading bot that scans Polymarket, researches markets using multi-source sentiment analysis, predicts outcomes with XGBoost + LLM calibration, and executes trades with risk management.

## Architecture

```
Scanner → Research → Prediction → Risk/Execution → Postmortem
```

- **Scanner** — Fetches active markets from Polymarket, filters by liquidity/volume/spread, flags opportunities
- **Research** — Multi-source sentiment analysis (NewsAPI, RSS feeds, Twitter, Reddit) with weighted aggregation
- **Predictor** — XGBoost model + Claude LLM calibration for probability estimation
- **Risk Manager** — Kelly criterion sizing, daily loss limits, position caps
- **Executor** — On-chain trade execution via Polymarket CLOB
- **Postmortem** — Analyzes settled trades, extracts lessons, suggests parameter updates

## Quick Start

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

```
ANTHROPIC_API_KEY=sk-...        # Required — Claude API for prediction calibration
POLYMARKET_PRIVATE_KEY=0x...    # Required for live trading
NEWSAPI_KEY=...                 # Optional — enhances research (free tier: 100 req/day)
REDDIT_CLIENT_ID=...            # Optional — Reddit sentiment source
REDDIT_CLIENT_SECRET=...
```

### 3. Set up Twitter (optional)

```bash
echo "username:password:email:email_password" > /tmp/accounts.txt
.venv/bin/twscrape add_accounts /tmp/accounts.txt "username:password:email:email_password"
.venv/bin/twscrape login_accounts
rm /tmp/accounts.txt
```

### 4. Run

```bash
# Single dry-run cycle
python run.py

# Continuous dry-run loop (every 5 minutes)
python run.py --loop

# Custom interval
python run.py --loop --interval=600

# Live trading (real money!)
python run.py --live

# Continuous live trading
python run.py --loop --live
```

## Commands

| Command | Description |
|---------|-------------|
| `python run.py` | Single dry-run cycle — scan, research, predict, evaluate |
| `python run.py --loop` | Continuous dry-run loop (default: every 300s) |
| `python run.py --loop --interval=N` | Loop with custom interval in seconds |
| `python run.py --live` | Single cycle with real trade execution |
| `python run.py --loop --live` | Continuous live trading |
| `python run.py --train` | Train XGBoost model on historical data |
| `python run.py --dashboard` | Launch terminal UI (Textual) |
| `python run.py --dashboard --loop` | Terminal UI with auto-cycling |
| `python run.py --web` | Launch web dashboard at http://127.0.0.1:8050 |
| `python run.py --web --live` | Web dashboard with live trading |

## Dashboards

### Web Dashboard

```bash
python run.py --web
```

Opens at http://127.0.0.1:8050. Features: PnL chart, trade history, market flags, live logs, settings panel, source weight configuration.

### Terminal Dashboard

```bash
python run.py --dashboard
```

Keybindings: `s` scan, `t` train, `l` toggle loop, `c` config, `q` quit.

## Research Sources

The bot aggregates sentiment from multiple weighted sources:

| Source | Weight | Auth Required |
|--------|--------|---------------|
| NewsAPI (top-headlines) | 1.0 | `NEWSAPI_KEY` |
| BBC, Al Jazeera, NPR, The Hill (RSS) | 0.9 | None |
| Polymarket Blog, Manifold Blog (RSS) | 0.8 | None |
| Google News (RSS) | 0.7 | None |
| Reddit | 0.6 | `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` |
| Twitter/X (twscrape) | 0.5 | twscrape account pool |

Sources without credentials are skipped automatically. The bot always works with at least Google News RSS (no auth needed).

Weights are configurable via environment variables:

```
SOURCE_WEIGHT_NEWSAPI=1.0
SOURCE_WEIGHT_RSS_MAJOR=0.9
SOURCE_WEIGHT_RSS_PREDICTION=0.8
SOURCE_WEIGHT_RSS_GOOGLE=0.7
SOURCE_WEIGHT_TWITTER=0.5
SOURCE_WEIGHT_REDDIT=0.6
RESEARCH_TIMEOUT=10
```

## Configuration

### Risk Parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `BANKROLL` | 1000 | Total bankroll in USD |
| `MAX_BET_FRACTION` | 0.05 | Max fraction of bankroll per bet |
| `MIN_EDGE_THRESHOLD` | 0.08 | Minimum edge to consider a trade |
| `CONFIDENCE_THRESHOLD` | 0.7 | Minimum confidence to approve a trade |
| `MAX_DAILY_LOSS` | 100 | Max daily loss before stopping |

### Scanner Parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `MIN_LIQUIDITY` | 5000 | Minimum market liquidity |
| `MIN_VOLUME_24H` | 1000 | Minimum 24h volume |
| `MAX_DAYS_TO_RESOLUTION` | 90 | Max days until market resolves |
| `SPREAD_ALERT_THRESHOLD` | 0.10 | Flag markets with wide spreads |
| `PRICE_MOVE_ALERT_THRESHOLD` | 0.15 | Flag markets with price spikes |

### Model Hyperparameters

| Variable | Default | Description |
|----------|---------|-------------|
| `XGB_N_ESTIMATORS` | 100 | XGBoost number of trees |
| `XGB_MAX_DEPTH` | 4 | Max tree depth |
| `XGB_LEARNING_RATE` | 0.1 | Learning rate |

## Testing

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## Project Structure

```
src/
  config.py              # Settings with pydantic validation
  db.py                  # SQLite database layer
  models.py              # Data models (ScannedMarket, Prediction, etc.)
  pipeline.py            # Main pipeline orchestrator
  scanner/
    scanner.py           # Polymarket market scanner
  research/
    base.py              # ResearchSource ABC + ResearchResult
    pipeline.py          # Research orchestrator (fan-out, dedup, weighted sentiment)
    newsapi.py           # NewsAPI source
    rss.py               # RSS feed registry (7 feeds) + relevance filtering
    twitter.py           # Twitter/X via twscrape
    reddit.py            # Reddit via praw
    sentiment.py         # VADER + RoBERTa sentiment analysis
  predictor/
    features.py          # Feature engineering
    xgb_model.py         # XGBoost model
    calibrator.py        # LLM probability calibration
    trainer.py           # Model training pipeline
  risk/
    risk_manager.py      # Kelly criterion + risk checks
    executor.py          # Polymarket CLOB trade execution
  postmortem/
    postmortem.py        # Trade analysis + lesson extraction
  dashboard/
    service.py           # Shared dashboard service layer
    terminal.py          # Textual terminal UI
    web.py               # FastAPI web UI
    log_handler.py       # In-memory log buffer
    templates/           # HTML templates
    static/              # CSS assets
```
