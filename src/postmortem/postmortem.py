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
                model=self.settings.POSTMORTEM_MODEL,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            try:
                report = json.loads(text)
            except json.JSONDecodeError:
                # Try to extract JSON from mixed text response
                import re
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    report = json.loads(json_match.group())
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
