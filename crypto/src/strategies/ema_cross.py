import math
import pandas as pd
from src.strategies.base import CryptoStrategy


class EMACrossStrategy(CryptoStrategy):
    def __init__(self, ema_fast: int = 5, ema_slow: int = 13):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow

    def _check_cross(self, prev_fast: float, prev_slow: float, curr_fast: float, curr_slow: float) -> int:
        if math.isnan(prev_fast) or math.isnan(prev_slow) or math.isnan(curr_fast) or math.isnan(curr_slow):
            return 0
        # Fast crosses above slow
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return 1
        # Fast crosses below slow
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            return -1
        return 0

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        if len(df) < 2:
            return 0, {}

        if "ema_fast" not in df.columns or "ema_slow" not in df.columns:
            return 0, {}

        prev_fast = float(df["ema_fast"].iloc[-2])
        prev_slow = float(df["ema_slow"].iloc[-2])
        curr_fast = float(df["ema_fast"].iloc[-1])
        curr_slow = float(df["ema_slow"].iloc[-1])

        signal = self._check_cross(prev_fast, prev_slow, curr_fast, curr_slow)
        return signal, {
            "prev_fast": prev_fast,
            "prev_slow": prev_slow,
            "curr_fast": curr_fast,
            "curr_slow": curr_slow,
        }

    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        trades = []
        for i in range(5, len(df), 5):
            if "ema_fast" not in df.columns or "ema_slow" not in df.columns:
                break

            prev_fast = float(df["ema_fast"].iloc[i - 2])
            prev_slow = float(df["ema_slow"].iloc[i - 2])
            curr_fast = float(df["ema_fast"].iloc[i - 1])
            curr_slow = float(df["ema_slow"].iloc[i - 1])

            signal = self._check_cross(prev_fast, prev_slow, curr_fast, curr_slow)
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
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
        }
