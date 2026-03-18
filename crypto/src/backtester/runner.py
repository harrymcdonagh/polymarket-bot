import json
import pandas as pd
from src.backtester.engine import BacktestEngine
from src.strategies import STRATEGY_REGISTRY

PARAM_GRID = {
    'macd_hist': [
        {'macd_fast': 3, 'macd_slow': 15, 'macd_signal': 3},
        {'macd_fast': 8, 'macd_slow': 21, 'macd_signal': 5},
        {'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9},
    ],
    'rsi_bb': [
        {'rsi_length': 7, 'bb_length': 20, 'bb_std': 2.0, 'rsi_oversold': 30, 'rsi_overbought': 70, 'squeeze_threshold': 0.02},
        {'rsi_length': 14, 'bb_length': 20, 'bb_std': 2.0, 'rsi_oversold': 25, 'rsi_overbought': 75, 'squeeze_threshold': 0.015},
    ],
    'vwap_cap': [
        {'vol_spike_min': 2.0, 'vwap_revert_pct': 0.001, 'vol_sma_length': 20},
        {'vol_spike_min': 3.0, 'vwap_revert_pct': 0.0005, 'vol_sma_length': 20},
    ],
    'ema_cross': [
        {'ema_fast': 5, 'ema_slow': 13},
        {'ema_fast': 8, 'ema_slow': 21},
        {'ema_fast': 3, 'ema_slow': 10},
    ],
}


class BacktestRunner:
    def __init__(self, db=None, entry_price: float = 0.50, fee_pct: float = 0.02, stake: float = 1.50):
        self.db = db
        self.engine = BacktestEngine(entry_price=entry_price, fee_pct=fee_pct, stake=stake)

    def run_grid(self, df: pd.DataFrame, strategies: list = None, symbol: str = "BTC") -> list[dict]:
        """Run all strategies x param combos. Save to DB if provided. Sort by expectancy desc."""
        strategy_names = strategies if strategies is not None else list(PARAM_GRID.keys())
        results = []

        for strat_name in strategy_names:
            if strat_name not in PARAM_GRID:
                continue
            if strat_name not in STRATEGY_REGISTRY:
                continue

            strat_cls = STRATEGY_REGISTRY[strat_name]
            param_combos = PARAM_GRID[strat_name]

            for params in param_combos:
                strategy = strat_cls(**params)
                metrics = self.engine.run(strategy, df, indicator_params=params)

                row = {
                    "strategy": strat_name,
                    "params": params,
                    "symbol": symbol,
                    **metrics,
                }
                results.append(row)

                if self.db is not None:
                    self.db.save_crypto_backtest(
                        strategy=strat_name,
                        params=json.dumps(params),
                        symbol=symbol,
                        total_trades=metrics["total_trades"],
                        win_rate=metrics["win_rate"],
                        expectancy=metrics["expectancy"],
                        total_pnl=metrics["total_pnl"],
                        max_drawdown=metrics["max_drawdown"],
                        profit_factor=metrics["profit_factor"],
                        sharpe=metrics["sharpe"],
                    )

        results.sort(key=lambda r: r["expectancy"], reverse=True)
        return results
