from src.strategies.macd_hist import MACDHistStrategy
from src.strategies.rsi_bb import RSIBBStrategy
from src.strategies.vwap_cap import VWAPCapStrategy
from src.strategies.ema_cross import EMACrossStrategy

STRATEGY_REGISTRY = {
    "macd_hist": MACDHistStrategy,
    "rsi_bb": RSIBBStrategy,
    "vwap_cap": VWAPCapStrategy,
    "ema_cross": EMACrossStrategy,
}
