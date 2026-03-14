import pytest
from datetime import datetime, timezone


def test_research_result_creation():
    from src.research.base import ResearchResult
    r = ResearchResult(
        text="Breaking: Event happened",
        link="https://example.com/1",
        published=datetime(2026, 3, 14, tzinfo=timezone.utc),
        source="test",
        weight=0.8,
    )
    assert r.text == "Breaking: Event happened"
    assert r.weight == 0.8
    assert r.source == "test"


def test_research_result_none_published():
    from src.research.base import ResearchResult
    r = ResearchResult(
        text="No date", link="", published=None, source="test", weight=1.0
    )
    assert r.published is None


def test_parse_published_rfc2822():
    from src.research.base import parse_published
    dt = parse_published("Wed, 12 Mar 2026 00:00:00 GMT")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 3


def test_parse_published_iso():
    from src.research.base import parse_published
    dt = parse_published("2026-03-12T15:30:00Z")
    assert dt is not None
    assert dt.year == 2026


def test_parse_published_garbage():
    from src.research.base import parse_published
    assert parse_published("not a date") is None
    assert parse_published("") is None


def test_research_source_abc():
    """ResearchSource cannot be instantiated directly."""
    from src.research.base import ResearchSource
    with pytest.raises(TypeError):
        ResearchSource()
