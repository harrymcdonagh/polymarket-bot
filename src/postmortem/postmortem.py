import json
import logging
import re
from datetime import datetime, timezone
import anthropic
from src.config import Settings
from src.db import Database

logger = logging.getLogger(__name__)

POSTMORTEM_PROMPT = """You are 5 postmortem analysts reviewing a prediction market trade that {outcome_description}. Each analyst has a different focus:

1. Data Quality Analyst: Was the input data sufficient, accurate, and timely?
2. Model Analyst: Did the XGBoost/LLM model make systematic errors?
3. Market Microstructure Analyst: Were there liquidity, timing, or execution issues?
4. Sentiment Analyst: Did sentiment analysis mislead the prediction?
5. Risk Analyst: Was the position sized correctly given uncertainty?

Trade details:
- Question: {question}
- Our predicted probability: {predicted_prob:.2%}
- Our side: {predicted_side}
- Actual outcome: {actual_outcome}
- Was correct: {was_correct}
- P&L: ${pnl:.2f}
- Our reasoning: {reasoning}

Previous lessons learned (avoid repeating):
{previous_lessons}

Each analyst should contribute. Return JSON:
{{
    "failure_reasons": ["reason1", "reason2", ...],
    "lessons": ["lesson1", "lesson2", ...],
    "system_updates": ["concrete change 1", "concrete change 2", ...],
    "category": "data_quality|model_error|market_structure|sentiment_error|risk_management|correct_prediction"
}}

Be specific and actionable. "system_updates" should be concrete parameter changes or logic modifications, not vague suggestions.
For CORRECT predictions: focus on what worked well and whether the win was due to skill or luck.
For WRONG predictions: focus on what went wrong and how to avoid the same mistake.
Return ONLY valid JSON."""

class PostmortemAnalyzer:
    def __init__(self, anthropic_client=None, settings: Settings | None = None, db: Database | None = None,
                 min_edge_to_analyze: float = 0.05):
        self.settings = settings or Settings()
        self.client = anthropic_client or anthropic.Anthropic(api_key=self.settings.ANTHROPIC_API_KEY)
        self.db = db
        self.min_edge_to_analyze = min_edge_to_analyze

    async def analyze_loss(
        self,
        question: str,
        predicted_prob: float,
        actual_outcome: str,
        pnl: float,
        reasoning: str,
        predicted_side: str = "unknown",
        was_correct: bool = False,
    ) -> dict:
        previous_lessons = ""
        if self.db:
            lessons = self.db.get_lessons()
            previous_lessons = "\n".join(f"- {l['lesson']}" for l in lessons[-20:])

        outcome_description = "was CORRECT" if was_correct else "was WRONG"

        prompt = POSTMORTEM_PROMPT.format(
            question=question,
            predicted_prob=predicted_prob,
            actual_outcome=actual_outcome,
            pnl=pnl,
            reasoning=reasoning,
            previous_lessons=previous_lessons or "None yet.",
            outcome_description=outcome_description,
            predicted_side=predicted_side,
            was_correct="Yes" if was_correct else "No",
        )

        try:
            response = self.client.messages.create(
                model=self.settings.POSTMORTEM_MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Strip markdown code fences if present
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```\s*$', '', text)
            text = text.strip()
            try:
                report = json.loads(text)
            except json.JSONDecodeError:
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    try:
                        report = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        logger.error(f"Postmortem returned invalid JSON: {text[:200]}")
                        report = {
                            "failure_reasons": ["LLM returned invalid JSON"],
                            "lessons": [f"Raw LLM response: {text[:300]}"],
                            "system_updates": [],
                            "category": "unknown",
                        }
                else:
                    logger.error(f"Postmortem returned non-JSON: {text[:200]}")
                    report = {
                        "failure_reasons": ["LLM returned non-JSON response"],
                        "lessons": [f"Raw LLM response: {text[:300]}"],
                        "system_updates": [],
                        "category": "unknown",
                    }
        except Exception as e:
            logger.error(f"Postmortem analysis failed: {e}")
            report = {
                "failure_reasons": [f"Postmortem analysis failed: {e}"],
                "lessons": ["Ensure LLM is available for postmortem analysis"],
                "system_updates": [],
                "category": "unknown",
            }

        if self.db:
            category = report.get("category", "unknown")
            for lesson in report.get("lessons", []):
                self.db.save_lesson(category=category, lesson=lesson)

        return report

    async def run_full_postmortem(self):
        """Analyze both wins AND losses from recently settled trades."""
        if not self.db:
            return []

        trades = self.db.get_all_settled_trades(limit=10)
        if not trades:
            return []

        # Compute Brier score for calibration tracking
        brier_scores = []
        for t in trades:
            pred_prob = t.get("predicted_prob")
            outcome = t.get("resolved_outcome")
            if pred_prob is not None and outcome in ("YES", "NO"):
                actual = 1.0 if outcome == "YES" else 0.0
                brier = (pred_prob - actual) ** 2
                brier_scores.append(brier)

        if brier_scores:
            avg_brier = sum(brier_scores) / len(brier_scores)
            logger.info(f"Calibration Brier score: {avg_brier:.4f} (lower is better, 0.25 = random)")
            # Market baseline: what if we just used market price?
            market_brier = []
            for t in trades:
                price = t.get("price")
                outcome = t.get("resolved_outcome")
                if price is not None and outcome in ("YES", "NO"):
                    actual = 1.0 if outcome == "YES" else 0.0
                    market_brier.append((price - actual) ** 2)
            if market_brier:
                avg_market = sum(market_brier) / len(market_brier)
                improvement = avg_market - avg_brier
                logger.info(
                    f"vs Market baseline: {avg_market:.4f} | "
                    f"Our improvement: {improvement:+.4f} ({'better' if improvement > 0 else 'worse'})"
                )

        # Only run LLM postmortem on surprising results (wrong AND high edge)
        reports = []
        for trade in trades:
            was_correct = trade.get("side") == trade.get("resolved_outcome")
            pnl = trade.get("hypothetical_pnl") or trade.get("pnl") or 0

            # Get the market question
            question = trade.get("market_id", "Unknown")
            if self.db:
                q = self.db.get_market_question(trade["market_id"])
                if q:
                    question = q

            # Analyze surprising outcomes (high-confidence wrong OR unexpected wins)
            pred = self.db.get_prediction_for_market(trade["market_id"]) if self.db else None
            edge = abs(pred.get("edge", 0)) if pred else 0

            if edge > self.min_edge_to_analyze:
                report = await self.analyze_loss(
                    question=question,
                    predicted_prob=trade.get("predicted_prob", 0.5),
                    actual_outcome=trade.get("resolved_outcome", "UNKNOWN"),
                    pnl=pnl,
                    reasoning=pred.get("reasoning", "See trade history") if pred else "See trade history",
                    predicted_side=trade.get("side", "unknown"),
                    was_correct=was_correct,
                )
                reports.append(report)

        return reports
