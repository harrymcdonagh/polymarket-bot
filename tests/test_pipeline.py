import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from src.pipeline import Pipeline
from src.config import Settings
from src.models import ScannedMarket, ScanFlag


def _mock_market():
    return ScannedMarket(
        condition_id="0xabc",
        question="Will X happen?",
        slug="will-x-happen",
        token_yes_id="tok_yes",
        token_no_id="tok_no",
        yes_price=0.55,
        no_price=0.45,
        spread=0.02,
        liquidity=50000,
        volume_24h=10000,
        end_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
        days_to_resolution=20,
        flags=[ScanFlag.HIGH_VOLUME],
        scanned_at=datetime.now(timezone.utc),
    )


_MOCK_SEARCH_RESULT = {
    "positive_ratio": 0.5,
    "negative_ratio": 0.3,
    "neutral_ratio": 0.2,
    "weighted_avg_score": 0.6,
    "sample_size": 5,
    "source_breakdown": {
        "rss_google": {
            "count": 5,
            "avg_score": 0.6,
            "positive_ratio": 0.5,
            "negative_ratio": 0.3,
            "neutral_ratio": 0.2,
        }
    },
}


@pytest.mark.asyncio
async def test_pipeline_scan_only_mode(tmp_path):
    settings = Settings(ANTHROPIC_API_KEY="test")

    with patch("src.pipeline.MarketScanner") as MockScanner:
        mock_scanner = MockScanner.return_value
        mock_market = MagicMock()
        mock_market.question = "Test market?"
        mock_market.flags = ["high_volume"]
        mock_market.condition_id = "0xabc"
        mock_scanner.scan = AsyncMock(return_value=[mock_market])

        pipeline = Pipeline(settings=settings, db_path=str(tmp_path / "test.db"))
        markets = await pipeline.scan()
        assert len(markets) == 1
        assert markets[0].question == "Test market?"


@pytest.mark.asyncio
async def test_pipeline_loads_model(tmp_path):
    settings = Settings(ANTHROPIC_API_KEY="test")
    pipeline = Pipeline(settings=settings, db_path=str(tmp_path / "test.db"))
    # Model should be initialized even without a saved file
    assert pipeline.xgb_model is not None


@pytest.mark.asyncio
async def test_pipeline_dry_run_cycle(tmp_path):
    """Test a full dry-run cycle with mocked scanner and research."""
    settings = Settings(ANTHROPIC_API_KEY="test")

    market = _mock_market()

    with patch("src.pipeline.MarketScanner") as MockScanner, \
         patch("src.pipeline.ResearchPipeline") as MockRP, \
         patch.object(Pipeline, "_generate_narrative", new_callable=AsyncMock, return_value="Test narrative"):

        MockScanner.return_value.scan = AsyncMock(return_value=[market])
        MockRP.return_value.search_and_analyze = AsyncMock(return_value=_MOCK_SEARCH_RESULT)

        pipeline = Pipeline(settings=settings, db_path=str(tmp_path / "test.db"))
        pipeline.postmortem = MagicMock()
        pipeline.postmortem.run_full_postmortem = AsyncMock(return_value=[])

        # Should complete without errors
        await pipeline.run_cycle(dry_run=True)


@pytest.mark.asyncio
async def test_pipeline_saves_snapshots(tmp_path):
    """Test that pipeline saves market snapshots during scan."""
    settings = Settings(ANTHROPIC_API_KEY="test")
    market = _mock_market()

    with patch("src.pipeline.MarketScanner") as MockScanner, \
         patch("src.pipeline.ResearchPipeline") as MockRP, \
         patch.object(Pipeline, "_generate_narrative", new_callable=AsyncMock, return_value="Test"):

        MockScanner.return_value.scan = AsyncMock(return_value=[market])
        MockRP.return_value.search_and_analyze = AsyncMock(return_value=_MOCK_SEARCH_RESULT)

        pipeline = Pipeline(settings=settings, db_path=str(tmp_path / "test.db"))
        pipeline.postmortem = MagicMock()
        pipeline.postmortem.run_full_postmortem = AsyncMock(return_value=[])

        await pipeline.run_cycle(dry_run=True)
        assert pipeline.db.get_snapshot_count() >= 1


@pytest.mark.asyncio
async def test_pipeline_no_executor_without_key(tmp_path):
    settings = Settings(ANTHROPIC_API_KEY="test", POLYMARKET_PRIVATE_KEY="")
    pipeline = Pipeline(settings=settings, db_path=str(tmp_path / "test.db"))
    assert pipeline.executor is None


@pytest.mark.asyncio
async def test_pipeline_uses_research_pipeline(tmp_path):
    """Pipeline.research() should delegate to ResearchPipeline."""
    from src.research.pipeline import ResearchPipeline

    settings = Settings(ANTHROPIC_API_KEY="test")

    with patch("src.pipeline.MarketScanner"):
        pipeline = Pipeline(settings=settings, db_path=str(tmp_path / "test.db"))

    assert hasattr(pipeline, "research_pipeline")
    assert isinstance(pipeline.research_pipeline, ResearchPipeline)


@pytest.mark.asyncio
async def test_pipeline_includes_structured_sources():
    """Verify pipeline initializes with structured pipeline."""
    settings = Settings()
    settings.SENTIMENT_USE_LLM = False  # disable for test
    pipe = Pipeline(settings=settings, db_path=":memory:")
    assert hasattr(pipe, "structured_pipeline")
    assert len(pipe.structured_pipeline.sources) == 5  # CLOB, CoinGecko, FRED, SportsData, Odds
