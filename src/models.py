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
