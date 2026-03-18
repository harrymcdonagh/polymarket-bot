import math
import pandas as pd
from src.strategies.base import CryptoStrategy


class RSIBBStrategy(CryptoStrategy):
    def __init__(
        self,
        rsi_length: int = 14,
        bb_length: int = 20,
        bb_std: float = 2.0,
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
        squeeze_threshold: float = 0.02,
    ):
        self.rsi_length = rsi_length
        self.bb_length = bb_length
        self.bb_std = bb_std
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.squeeze_threshold = squeeze_threshold

    def _check_signal(self, rsi: float, bb_bandwidth: float) -> int:
        if math.isnan(rsi) or math.isnan(bb_bandwidth):
            return 0
        squeeze = bb_bandwidth < self.squeeze_threshold
        if squeeze and rsi < self.rsi_oversold:
            return 1
        elif squeeze and rsi > self.rsi_overbought:
            return -1
        return 0

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        if len(df) < 1:
            return 0, {}

        if "rsi" not in df.columns or "bb_bandwidth" not in df.columns:
            return 0, {}

        rsi = float(df["rsi"].iloc[-1])
        bb_bandwidth = float(df["bb_bandwidth"].iloc[-1])

        signal = self._check_signal(rsi, bb_bandwidth)
        return signal, {"rsi": rsi, "bb_bandwidth": bb_bandwidth}

    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        trades = []
        for i in range(5, len(df), 5):
            if "rsi" not in df.columns or "bb_bandwidth" not in df.columns:
                break

            rsi = float(df["rsi"].iloc[i - 1])
            bb_bandwidth = float(df["bb_bandwidth"].iloc[i - 1])

            signal = self._check_signal(rsi, bb_bandwidth)
            if signal == 0:
                continue

            entry_idx = i
            exit_idx = min(i + 5, len(df) - 1)
            trades.append({
                "signal": signal,
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "entry_price": float(df["close"].iloc[entry_idx]),
                "exit_price": float(df["close"].iloc[exit_idx]),
            })

        return trades

    def params_dict(self) -> dict:
        return {
            "rsi_length": self.rsi_length,
            "bb_length": self.bb_length,
            "bb_std": self.bb_std,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "squeeze_threshold": self.squeeze_threshold,
        }
