from src.research.sentiment import SentimentAnalyzer


def test_positive_sentiment():
    analyzer = SentimentAnalyzer(use_transformer=False)  # VADER only for tests
    result = analyzer.analyze("This is absolutely amazing and wonderful!")
    assert result["label"] == "positive"
    assert result["score"] > 0.5


def test_negative_sentiment():
    analyzer = SentimentAnalyzer(use_transformer=False)
    result = analyzer.analyze("This is terrible and awful, complete disaster.")
    assert result["label"] == "negative"
    assert result["score"] > 0.5


def test_batch_sentiment():
    analyzer = SentimentAnalyzer(use_transformer=False)
    texts = ["Great news!", "Terrible outcome", "The weather is okay"]
    results = analyzer.analyze_batch(texts)
    assert len(results) == 3
    assert results[0]["label"] == "positive"
    assert results[1]["label"] == "negative"
