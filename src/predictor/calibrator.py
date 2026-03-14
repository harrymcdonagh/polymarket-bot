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
