from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import ScannedMarket


class StructuredDataSource(ABC):
    """Base class for structured (numeric) data sources."""

    name: str

    @abstractmethod
    async def fetch(self, market: ScannedMarket) -> dict[str, float]:
        """Fetch structured numeric signals for the given market."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this source is configured and usable."""
