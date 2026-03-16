import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from src.research.base import ResearchResult


def _make_result(text, source="test", weight=1.0):
    return ResearchResult(
        text=text, link="", published=datetime(2026, 3, 14, tzinfo=timezone.utc),
        source=source, weight=weight,
    )


def test_dedup_keeps_highest_weight():
    from src.research.pipeline import deduplicate
    results = [
        _make_result("US Election Results Show Surprise", source="rss_google", weight=0.7),
        _make_result("US Election Results Show Surprise Outcome", source="rss_bbc", weight=0.9),
    ]
    deduped = deduplicate(results, threshold=0.85)
    assert len(deduped) == 1
    assert deduped[0].source == "rss_bbc"


def test_dedup_keeps_different_articles():
    from src.research.pipeline import deduplicate
    results = [
        _make_result("US Election Results", source="a", weight=0.7),
        _make_result("Crypto Market Crash", source="b", weight=0.9),
    ]
    deduped = deduplicate(results, threshold=0.85)
    assert len(deduped) == 2


@pytest.mark.asyncio
async def test_pipeline_search_fans_out():
    from src.research.pipeline import ResearchPipeline

    source1 = MagicMock()
    source1.is_available.return_value = True
    source1.name = "src1"
    source1.search = AsyncMock(return_value=[_make_result("Result 1", "src1", 0.9)])

    source2 = MagicMock()
    source2.is_available.return_value = True
    source2.name = "src2"
    source2.search = AsyncMock(return_value=[_make_result("Result 2", "src2", 0.7)])

    pipeline = ResearchPipeline(sources=[source1, source2], timeout=10)
    results = await pipeline.search("test query")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_pipeline_skips_unavailable_sources():
    from src.research.pipeline import ResearchPipeline

    available = MagicMock()
    available.is_available.return_value = True
    available.name = "available"
    available.search = AsyncMock(return_value=[_make_result("Got it", "available")])

    unavailable = MagicMock()
    unavailable.is_available.return_value = False
    unavailable.name = "unavailable"

    pipeline = ResearchPipeline(sources=[available, unavailable], timeout=10)
    results = await pipeline.search("test")
    assert len(results) == 1
    unavailable.search.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_handles_source_timeout():
    from src.research.pipeline import ResearchPipeline
    import asyncio

    slow_source = MagicMock()
    slow_source.is_available.return_value = True
    slow_source.name = "slow"

    async def slow_search(query):
        await asyncio.sleep(10)
        return []

    slow_source.search = slow_search

    fast_source = MagicMock()
    fast_source.is_available.return_value = True
    fast_source.name = "fast"
    fast_source.search = AsyncMock(return_value=[_make_result("Fast result")])

    pipeline = ResearchPipeline(sources=[slow_source, fast_source], timeout=0.1)
    results = await pipeline.search("test")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_pipeline_weighted_sentiment():
    from src.research.pipeline import ResearchPipeline

    source = MagicMock()
    source.is_available.return_value = True
    source.name = "test"
    source.search = AsyncMock(return_value=[
        _make_result("Great positive news!", "newsapi", 1.0),
        _make_result("Terrible negative news!", "twitter", 0.5),
    ])

    mock_analyzer = MagicMock()
    mock_analyzer.analyze_batch_async = AsyncMock(return_value=[
        {"label": "positive", "score": 0.9},
        {"label": "negative", "score": 0.8},
    ])

    pipeline = ResearchPipeline(sources=[source], timeout=10, sentiment_analyzer=mock_analyzer)
    sentiment = await pipeline.search_and_analyze("test")

    assert "weighted_avg_score" in sentiment
    assert "source_breakdown" in sentiment
    assert sentiment["sample_size"] == 2


@pytest.mark.asyncio
async def test_pipeline_empty_results():
    from src.research.pipeline import ResearchPipeline

    source = MagicMock()
    source.is_available.return_value = True
    source.name = "empty"
    source.search = AsyncMock(return_value=[])

    pipeline = ResearchPipeline(sources=[source], timeout=10)
    sentiment = await pipeline.search_and_analyze("nothing")
    assert sentiment["sample_size"] == 0
    assert sentiment["weighted_avg_score"] == 0
