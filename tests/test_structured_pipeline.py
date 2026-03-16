import pytest
from unittest.mock import AsyncMock, MagicMock
from src.research.structured_base import StructuredDataSource
from src.research.structured_pipeline import StructuredDataPipeline


class FakeSource(StructuredDataSource):
    name = "fake"
    async def fetch(self, market) -> dict[str, float]:
        return {"fake_value": 1.0}
    def is_available(self): return True


class FailingSource(StructuredDataSource):
    name = "failing"
    async def fetch(self, market) -> dict[str, float]:
        raise RuntimeError("API down")
    def is_available(self): return True


class UnavailableSource(StructuredDataSource):
    name = "unavailable"
    async def fetch(self, market) -> dict[str, float]:
        return {"should_not_appear": 99.0}
    def is_available(self): return False


def test_structured_source_abc():
    source = FakeSource()
    assert source.name == "fake"
    assert source.is_available() is True


@pytest.mark.asyncio
async def test_structured_source_fetch():
    source = FakeSource()
    market = MagicMock()
    result = await source.fetch(market)
    assert result == {"fake_value": 1.0}


@pytest.mark.asyncio
async def test_pipeline_merges_sources():
    class SourceA(StructuredDataSource):
        name = "a"
        async def fetch(self, market): return {"a_val": 1.0}
        def is_available(self): return True
    class SourceB(StructuredDataSource):
        name = "b"
        async def fetch(self, market): return {"b_val": 2.0}
        def is_available(self): return True
    pipeline = StructuredDataPipeline(sources=[SourceA(), SourceB()])
    result = await pipeline.fetch(MagicMock())
    assert result == {"a_val": 1.0, "b_val": 2.0}


@pytest.mark.asyncio
async def test_pipeline_handles_failure():
    pipeline = StructuredDataPipeline(sources=[FakeSource(), FailingSource()])
    result = await pipeline.fetch(MagicMock())
    assert result == {"fake_value": 1.0}


@pytest.mark.asyncio
async def test_pipeline_skips_unavailable():
    pipeline = StructuredDataPipeline(sources=[FakeSource(), UnavailableSource()])
    result = await pipeline.fetch(MagicMock())
    assert "should_not_appear" not in result
    assert result == {"fake_value": 1.0}
