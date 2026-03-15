import pytest
from src.config import Settings


def test_source_weight_defaults():
    s = Settings()
    assert s.SOURCE_WEIGHT_NEWSAPI == 1.0
    assert s.SOURCE_WEIGHT_RSS_MAJOR == 0.9
    assert s.SOURCE_WEIGHT_TWITTER == 0.5


def test_source_weight_rejects_zero():
    with pytest.raises(Exception):
        Settings(SOURCE_WEIGHT_NEWSAPI=0.0)


def test_source_weight_rejects_over_one():
    with pytest.raises(Exception):
        Settings(SOURCE_WEIGHT_NEWSAPI=1.5)


def test_source_weight_accepts_valid():
    s = Settings(SOURCE_WEIGHT_NEWSAPI=0.5)
    assert s.SOURCE_WEIGHT_NEWSAPI == 0.5


def test_newsapi_key_default_empty():
    s = Settings()
    assert s.NEWSAPI_KEY == ""


def test_research_timeout_default():
    s = Settings()
    assert s.RESEARCH_TIMEOUT == 10
