from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)


@dataclass
class ResearchResult:
    text: str
    link: str
    published: datetime | None
    source: str
    weight: float


def parse_published(date_str: str) -> datetime | None:
    """Parse various date formats into datetime. Returns None on failure."""
    if not date_str:
        return None
    # Try RFC 2822 (RSS standard)
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # Try ISO 8601
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


class ResearchSource(ABC):
    """Base class for all research sources."""

    name: str
    default_weight: float

    @abstractmethod
    async def search(self, query: str) -> list[ResearchResult]:
        """Search this source for the given query."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this source is configured and usable."""
