import pandas as pd
import pandas_ta as ta


def compute_indicators(
    df: pd.DataFrame,
    macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9,
    rsi_length: int = 14,
    bb_length: int = 20, bb_std: float = 2.0,
    ema_fast: int = 5, ema_slow: int = 13,
    vol_sma_length: int = 20,
    atr_length: int = 14,
) -> pd.DataFrame:
    """Compute all technical indicators on a 1m candle DataFrame."""
    df = df.copy()

    # MACD
    macd_result = ta.macd(df["close"], fast=macd_fast, slow=macd_slow, signal=macd_signal)
    if macd_result is not None and len(macd_result.columns) >= 3:
        df["macd"] = macd_result.iloc[:, 0]
        df["macd_hist"] = macd_result.iloc[:, 1]
        df["macd_signal"] = macd_result.iloc[:, 2]
    else:
        df["macd"] = df["macd_hist"] = df["macd_signal"] = float("nan")

    # RSI
    rsi = ta.rsi(df["close"], length=rsi_length)
    df["rsi"] = rsi if rsi is not None else float("nan")

    # Bollinger Bands
    bbands = ta.bbands(df["close"], length=bb_length, std=bb_std)
    if bbands is not None and len(bbands.columns) >= 3:
        df["bb_lower"] = bbands.iloc[:, 0]
        df["bb_mid"] = bbands.iloc[:, 1]
        df["bb_upper"] = bbands.iloc[:, 2]
        df["bb_bandwidth"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    else:
        df["bb_lower"] = df["bb_mid"] = df["bb_upper"] = df["bb_bandwidth"] = float("nan")

    # VWAP
    df["vwap"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])

    # EMA pair
    df["ema_fast"] = ta.ema(df["close"], length=ema_fast)
    df["ema_slow"] = ta.ema(df["close"], length=ema_slow)

    # Volume SMA + spike ratio
    df["vol_sma"] = ta.sma(df["volume"], length=vol_sma_length)
    df["vol_spike_ratio"] = df["volume"] / df["vol_sma"]

    # ATR
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=atr_length)

    return df
