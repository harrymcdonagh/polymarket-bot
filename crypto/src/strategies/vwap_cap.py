import math
import pandas as pd
from src.strategies.base import CryptoStrategy


class VWAPCapStrategy(CryptoStrategy):
    def __init__(
        self,
        vol_spike_min: float = 2.0,
        vwap_revert_pct: float = 0.001,
        vol_sma_length: int = 20,
    ):
        self.vol_spike_min = vol_spike_min
        self.vwap_revert_pct = vwap_revert_pct
        self.vol_sma_length = vol_sma_length

    def _check_signal(self, vol_spike_ratio: float, close: float, vwap: float) -> int:
        if vol_spike_ratio is None or close is None or vwap is None:
            return 0
        if math.isnan(vol_spike_ratio) or math.isnan(close) or math.isnan(vwap):
            return 0

        spike = vol_spike_ratio >= self.vol_spike_min
        if not spike:
            return 0

        deviation = (close - vwap) / vwap
        if deviation < -self.vwap_revert_pct:
            return 1
        elif deviation > self.vwap_revert_pct:
            return -1
        return 0

    def generate_signal(self, df: pd.DataFrame) -> tuple[int, dict]:
        if len(df) < 1:
            return 0, {}

        if "vol_spike_ratio" not in df.columns or "vwap" not in df.columns:
            return 0, {}

        raw_vsr = df["vol_spike_ratio"].iloc[-1]
        raw_close = df["close"].iloc[-1]
        raw_vwap = df["vwap"].iloc[-1]

        vol_spike_ratio = None if raw_vsr is None else float(raw_vsr)
        close = None if raw_close is None else float(raw_close)
        vwap = None if raw_vwap is None else float(raw_vwap)

        signal = self._check_signal(vol_spike_ratio, close, vwap)
        return signal, {"vol_spike_ratio": vol_spike_ratio, "close": close, "vwap": vwap}

    def backtest_signal(self, df: pd.DataFrame) -> list[dict]:
        trades = []
        for i in range(5, len(df), 5):
            if "vol_spike_ratio" not in df.columns or "vwap" not in df.columns:
                break

            raw_vsr = df["vol_spike_ratio"].iloc[i - 1]
            raw_close = df["close"].iloc[i - 1]
            raw_vwap = df["vwap"].iloc[i - 1]

            vol_spike_ratio = None if raw_vsr is None else float(raw_vsr)
            close = None if raw_close is None else float(raw_close)
            vwap = None if raw_vwap is None else float(raw_vwap)

            signal = self._check_signal(vol_spike_ratio, close, vwap)
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
            "vol_spike_min": self.vol_spike_min,
            "vwap_revert_pct": self.vwap_revert_pct,
            "vol_sma_length": self.vol_sma_length,
        }
