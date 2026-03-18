from abc import ABC, abstractmethod
import pandas as pd


class CryptoStrategy(ABC):
    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        """Returns (signal, metadata). signal: 1=YES/long, -1=NO/short, 0=no trade."""
        ...

    @abstractmethod
    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        """Walk DataFrame at 5-min boundaries. Returns list of trade dicts."""
        ...

    @abstractmethod
    def params_dict(self) -> dict:
        ...
