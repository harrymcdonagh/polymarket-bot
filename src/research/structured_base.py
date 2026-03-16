from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import ScannedMarket


class StructuredDataSource(ABC):
    name: str

    @abstractmethod
    async def fetch(self, market: ScannedMarket) -> dict[str, float]: ...

    @abstractmethod
    def is_available(self) -> bool: ...
