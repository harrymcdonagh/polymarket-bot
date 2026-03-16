# src/research/sentiment.py
import asyncio
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

            # Scale max_tokens with batch size (~30 tokens per result)
            max_tok = max(300, len(texts) * 35 + 50)

            # Run sync Anthropic client in thread to avoid blocking event loop
            response = await asyncio.to_thread(
                client.messages.create,
                model=self.sentiment_model,
                max_tokens=max_tok,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            # Strip markdown code fences
            if text.startswith("```"):
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```\s*$', '', text)

            try:
                results = json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match:
                    results = json.loads(match.group())
                else:
                    logger.warning(f"Haiku returned non-JSON: {text[:200]}")
                    return None

            if not isinstance(results, list) or len(results) != len(texts):
                logger.warning(f"Haiku returned {len(results) if isinstance(results, list) else 'non-list'} results for {len(texts)} texts")
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
