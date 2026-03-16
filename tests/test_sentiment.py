# tests/test_sentiment.py
import pytest
from unittest.mock import MagicMock
from src.research.sentiment import SentimentAnalyzer


def test_positive_sentiment():
    analyzer = SentimentAnalyzer(use_llm=False)
    result = analyzer.analyze("This is absolutely amazing and wonderful!")
    assert result["label"] == "positive"
    assert result["score"] > 0.5


def test_negative_sentiment():
    analyzer = SentimentAnalyzer(use_llm=False)
    result = analyzer.analyze("This is terrible and awful, complete disaster.")
    assert result["label"] == "negative"
    assert result["score"] < -0.5


def test_batch_sentiment():
    analyzer = SentimentAnalyzer(use_llm=False)
    texts = ["Great news!", "Terrible outcome", "The weather is okay"]
    results = analyzer.analyze_batch(texts)
    assert len(results) == 3
    assert results[0]["label"] == "positive"
    assert results[1]["label"] == "negative"


@pytest.mark.asyncio
async def test_async_batch_vader_only():
    analyzer = SentimentAnalyzer(use_llm=False)
    results = await analyzer.analyze_batch_async(
        ["Great news!", "Terrible outcome"],
        market_question="Will X happen?",
    )
    assert len(results) == 2
    assert results[0]["label"] == "positive"
    assert results[1]["label"] == "negative"


@pytest.mark.asyncio
async def test_async_batch_haiku_for_ambiguous():
    analyzer = SentimentAnalyzer(use_llm=True, llm_threshold=0.4)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = '[{"label":"positive","score":0.6}]'
    mock_client.messages.create.return_value = mock_response
    analyzer._anthropic = mock_client

    results = await analyzer.analyze_batch_async(
        ["The meeting discussed results"],
        market_question="Will GDP grow?",
    )
    assert len(results) == 1
    assert results[0]["label"] == "positive"
    assert results[0]["score"] == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_async_batch_haiku_fallback_on_error():
    analyzer = SentimentAnalyzer(use_llm=True, llm_threshold=0.4)
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API down")
    analyzer._anthropic = mock_client

    results = await analyzer.analyze_batch_async(
        ["The meeting discussed results"],
        market_question="Will GDP grow?",
    )
    assert len(results) == 1
    assert "label" in results[0]
    assert "score" in results[0]


def test_legacy_compat_params():
    """Old constructor params (use_transformer, ambiguity_threshold) still work."""
    analyzer = SentimentAnalyzer(use_transformer=False, ambiguity_threshold=0.6)
    result = analyzer.analyze("Great news!")
    assert result["label"] == "positive"
