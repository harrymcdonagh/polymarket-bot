import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.pipeline import Pipeline
from src.config import Settings

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
