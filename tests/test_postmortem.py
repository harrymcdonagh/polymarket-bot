import pytest
from unittest.mock import MagicMock, AsyncMock
from src.postmortem.postmortem import PostmortemAnalyzer

@pytest.mark.asyncio
async def test_postmortem_generates_report():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="""{
        "failure_reasons": ["Sentiment data was stale", "Market had low sample size"],
        "lessons": ["Weight recent sentiment higher", "Require minimum 30 data points"],
        "system_updates": ["Increase MIN_SENTIMENT_SAMPLES to 30", "Add recency weighting to sentiment"],
        "category": "data_quality"
    }""")]

    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=mock_response)

    analyzer = PostmortemAnalyzer(anthropic_client=mock_client)
    report = await analyzer.analyze_loss(
        question="Will X happen?",
        predicted_prob=0.70,
        actual_outcome="NO",
        pnl=-50.0,
        reasoning="Strong sentiment suggested YES",
    )
    assert len(report["failure_reasons"]) > 0
    assert len(report["lessons"]) > 0
    assert len(report["system_updates"]) > 0
