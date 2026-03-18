import math
import pandas as pd
from src.strategies.base import CryptoStrategy


class MACDHistStrategy(CryptoStrategy):
    def __init__(self, macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9):
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        if len(df) < 2:
            return 0, {}

        if "macd_hist" not in df.columns:
            return 0, {}

        prev = df["macd_hist"].iloc[-2]
        curr = df["macd_hist"].iloc[-1]

        if math.isnan(prev) or math.isnan(curr):
            return 0, {"reason": "nan"}

        if prev <= 0 and curr > 0:
            return 1, {"prev_hist": prev, "curr_hist": curr}
        elif prev >= 0 and curr < 0:
            return -1, {"prev_hist": prev, "curr_hist": curr}
        return 0, {"prev_hist": prev, "curr_hist": curr}

    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        trades = []
        for i in range(5, len(df), 5):
            prev = df["macd_hist"].iloc[i - 2]
            curr = df["macd_hist"].iloc[i - 1]

            if math.isnan(prev) or math.isnan(curr):
                continue

            if prev <= 0 and curr > 0:
                signal = 1
            elif prev >= 0 and curr < 0:
                signal = -1
            else:
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
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
        }
