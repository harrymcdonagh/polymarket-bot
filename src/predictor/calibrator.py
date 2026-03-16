import json
import logging
import re
from datetime import datetime, timezone
import anthropic
from src.models import ScannedMarket, ResearchReport, Prediction
from src.config import Settings

logger = logging.getLogger(__name__)

CALIBRATION_PROMPT = """You are an expert superforecaster calibrating prediction market probabilities. Use structured reasoning to estimate the TRUE probability of this event.

**Market:** {question}
**Current YES price:** {yes_price} (market implied probability)
**Current NO price:** {no_price}
**Spread:** {spread}
**Liquidity:** ${liquidity:,.0f}
**24h Volume:** ${volume:,.0f}
**Days to resolution:** {days_to_resolution}

**XGBoost model estimate:** {xgb_probability}

**Research summary:**
{narrative_summary}

**Sentiment data:**
{sentiment_summary}

{lessons_context}

**Instructions — follow this reasoning chain:**

1. **Reference class**: What category does this event fall into? (e.g., political elections, crypto price targets, regulatory decisions). What's the historical base rate for this type of event?

2. **Prior estimate**: Based on the reference class and base rate alone (ignoring current evidence), what probability would you assign? Start from the market price as an anchor since markets aggregate information.

3. **Evidence update**: For each piece of new evidence (research, sentiment, XGBoost estimate), how much should it shift the probability? Be specific about direction and magnitude. Remember: one strong signal beats many weak ones.

4. **Contrarian check**: What would someone betting the OTHER side argue? Is there a strong case you're missing? Markets are efficient — you need a specific reason why the market price is wrong.

5. **Final estimate**: Your calibrated probability with a confidence band.

Return JSON:
{{
  "probability": 0.XX,
  "confidence_lower": 0.XX,
  "confidence_upper": 0.XX,
  "reasoning": "your step-by-step analysis"
}}

Rules:
- probability must be between 0.01 and 0.99
- confidence_lower/upper define your 80% confidence interval
- Be well-calibrated: when you say 70%, it should resolve YES ~70% of the time
- If evidence is weak or conflicting, stay close to the market price
- Large deviations from market price (>15%) need strong justification

Return ONLY valid JSON."""


class Calibrator:
    def __init__(self, anthropic_client=None, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.client = anthropic_client or anthropic.Anthropic(api_key=self.settings.ANTHROPIC_API_KEY)

    async def calibrate(
        self, market: ScannedMarket, research: ResearchReport, xgb_probability: float,
        lessons: list[str] | None = None,
    ) -> Prediction:
        """Combine XGBoost prediction with LLM calibration."""
        sentiment_lines = []
        for s in research.sentiments:
            sentiment_lines.append(
                f"  {s.source}: +{s.positive_ratio:.0%} / -{s.negative_ratio:.0%} "
                f"(n={s.sample_size}, avg={s.avg_compound_score:.2f})"
            )
        sentiment_summary = "\n".join(sentiment_lines) if sentiment_lines else "No sentiment data available"

        # Format lessons context if available
        if lessons:
            lessons_text = "\n".join(f"- {l}" for l in lessons[-10:])
            lessons_context = f"**Previous lessons learned (avoid repeating past mistakes):**\n{lessons_text}"
        else:
            lessons_context = ""

        prompt = CALIBRATION_PROMPT.format(
            question=market.question,
            yes_price=market.yes_price,
            no_price=market.no_price,
            spread=market.spread,
            liquidity=market.liquidity,
            volume=market.volume_24h,
            days_to_resolution=market.days_to_resolution or "unknown",
            xgb_probability=f"{xgb_probability:.2%}" if xgb_probability is not None else "No trained model",
            narrative_summary=research.narrative_summary,
            sentiment_summary=sentiment_summary,
            lessons_context=lessons_context,
        )

        llm_failed = False
        llm_uncertainty = 0.15  # default uncertainty band
        try:
            response = self.client.messages.create(
                model=self.settings.CALIBRATION_MODEL,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Parse JSON — try direct, then regex extraction
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    raise ValueError(f"No JSON found in LLM response: {text[:200]}")

            llm_probability = max(0.01, min(0.99, float(data["probability"])))
            reasoning = data.get("reasoning", "")

            # Extract uncertainty from confidence interval
            lower = data.get("confidence_lower")
            upper = data.get("confidence_upper")
            if lower is not None and upper is not None:
                llm_uncertainty = (float(upper) - float(lower)) / 2.0
            else:
                # No interval provided — estimate from distance to market price
                llm_uncertainty = min(0.25, abs(llm_probability - market.yes_price) * 0.5 + 0.05)

        except Exception as e:
            logger.error(f"LLM calibration failed: {e} — prediction will have reduced confidence")
            llm_probability = xgb_probability if xgb_probability is not None else market.yes_price
            reasoning = f"LLM calibration failed ({e}), using fallback estimate"
            llm_failed = True
            llm_uncertainty = 0.30

        # Combine predictions: if XGB is trained, blend 40/60; otherwise LLM only
        if xgb_probability is not None:
            predicted_prob = 0.4 * xgb_probability + 0.6 * llm_probability
            model_agreement = 1.0 - abs(xgb_probability - llm_probability)
        else:
            predicted_prob = llm_probability
            model_agreement = 0.5  # moderate confidence without XGB cross-check

        # Reduce confidence when LLM failed
        if llm_failed:
            model_agreement = 0.1

        # Determine side and edge
        if predicted_prob > market.yes_price:
            side = "YES"
            edge = predicted_prob - market.yes_price
        else:
            side = "NO"
            edge = market.yes_price - predicted_prob

        # Confidence: blend model agreement, edge strength, and LLM certainty
        # Low LLM uncertainty = high confidence; high agreement = high confidence
        llm_certainty = max(0.0, 1.0 - llm_uncertainty * 4)  # 0.25 uncertainty → 0.0 certainty
        edge_signal = min(1.0, abs(edge) * 5)
        confidence = min(1.0, (
            model_agreement * 0.35 +
            edge_signal * 0.30 +
            llm_certainty * 0.35
        ))

        return Prediction(
            market_id=market.condition_id,
            question=market.question,
            market_yes_price=market.yes_price,
            predicted_probability=predicted_prob,
            xgb_probability=xgb_probability if xgb_probability is not None else predicted_prob,
            llm_probability=llm_probability,
            edge=edge,
            confidence=confidence,
            recommended_side=side,
            reasoning=reasoning,
            predicted_at=datetime.now(timezone.utc),
        )
