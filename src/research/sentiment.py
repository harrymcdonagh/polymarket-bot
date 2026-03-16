import logging
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    def __init__(self, use_transformer: bool = True, ambiguity_threshold: float = 0.6):
        self.vader = SentimentIntensityAnalyzer()
        self.use_transformer = use_transformer
        self.ambiguity_threshold = ambiguity_threshold
        self._roberta = None

    def _get_roberta(self):
        if self._roberta is None:
            from transformers import pipeline
            self._roberta = pipeline(
                "sentiment-analysis",
                model="cardiffnlp/twitter-roberta-base-sentiment-latest",
            )
        return self._roberta

    def analyze(self, text: str) -> dict:
        """Analyze sentiment of a single text. Returns {label, score}."""
        vader_scores = self.vader.polarity_scores(text)
        compound = vader_scores["compound"]

        # Fast path: VADER is confident
        if not self.use_transformer or abs(compound) > self.ambiguity_threshold:
            label = "positive" if compound > 0.05 else ("negative" if compound < -0.05 else "neutral")
            return {"label": label, "score": compound}

        # Slow path: use RoBERTa for ambiguous cases
        try:
            roberta = self._get_roberta()
            result = roberta(text[:512])[0]  # truncate for model
            return {"label": result["label"].lower(), "score": result["score"]}
        except Exception as e:
            logger.warning(f"RoBERTa failed, falling back to VADER: {e}")
            label = "positive" if compound > 0.05 else ("negative" if compound < -0.05 else "neutral")
            return {"label": label, "score": compound}

    def analyze_batch(self, texts: list[str]) -> list[dict]:
        """Analyze sentiment of multiple texts."""
        return [self.analyze(text) for text in texts]

    def aggregate(self, results: list[dict]) -> dict:
        """Compute aggregate sentiment stats from a list of results."""
        if not results:
            return {"positive_ratio": 0, "negative_ratio": 0, "neutral_ratio": 0, "avg_score": 0, "sample_size": 0}

        pos = sum(1 for r in results if r["label"] == "positive")
        neg = sum(1 for r in results if r["label"] == "negative")
        neu = sum(1 for r in results if r["label"] == "neutral")
        total = len(results)
        avg_score = sum(r["score"] for r in results) / total

        return {
            "positive_ratio": pos / total,
            "negative_ratio": neg / total,
            "neutral_ratio": neu / total,
            "avg_score": avg_score,
            "sample_size": total,
        }
