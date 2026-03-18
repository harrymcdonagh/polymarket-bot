import numpy as np
import pandas as pd
from src.indicators import compute_indicators


class BacktestEngine:
    def __init__(self, entry_price: float = 0.50, fee_pct: float = 0.02, stake: float = 1.50):
        self.entry_price = entry_price
        self.fee_pct = fee_pct
        self.stake = stake

    def _calc_trade_pnl(self, won: bool) -> float:
        fee = self.stake * self.fee_pct
        if won:
            return (1.0 / self.entry_price - 1.0) * self.stake - fee
        else:
            return -self.stake - fee

    def run(self, strategy, df: pd.DataFrame, indicator_params: dict = None) -> dict:
        """Run backtest. Computes indicators, generates backtest signals, scores results.

        Returns dict with: total_trades, win_rate, expectancy, total_pnl,
        max_drawdown, profit_factor, sharpe
        """
        params = indicator_params or {}
        enriched = compute_indicators(df, **params)

        trades = strategy.backtest_signal(enriched)

        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "expectancy": 0.0,
                "total_pnl": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "sharpe": 0.0,
            }

        pnl_list = []
        wins = 0
        for trade in trades:
            signal = trade["signal"]
            entry_price = trade["entry_price"]
            exit_price = trade["exit_price"]

            if signal == 1:
                won = exit_price > entry_price
            elif signal == -1:
                won = exit_price < entry_price
            else:
                continue

            pnl = self._calc_trade_pnl(won)
            pnl_list.append(pnl)
            if won:
                wins += 1

        n = len(pnl_list)
        if n == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "expectancy": 0.0,
                "total_pnl": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "sharpe": 0.0,
            }

        pnl_arr = np.array(pnl_list)
        total_pnl = float(pnl_arr.sum())
        win_rate = wins / n
        expectancy = float(pnl_arr.mean())

        # Max drawdown from cumulative PnL curve
        cum = np.cumsum(pnl_arr)
        running_max = np.maximum.accumulate(cum)
        drawdowns = running_max - cum
        max_drawdown = float(drawdowns.max())

        # Profit factor: gross wins / gross losses
        gross_wins = float(pnl_arr[pnl_arr > 0].sum()) if (pnl_arr > 0).any() else 0.0
        gross_losses = float(abs(pnl_arr[pnl_arr < 0].sum())) if (pnl_arr < 0).any() else 0.0
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")

        # Sharpe (annualised using 5-min periods: ~105120 per year)
        std = float(pnl_arr.std())
        sharpe = (expectancy / std * np.sqrt(105120)) if std > 0 else 0.0

        return {
            "total_trades": n,
            "win_rate": win_rate,
            "expectancy": expectancy,
            "total_pnl": total_pnl,
            "max_drawdown": max_drawdown,
            "profit_factor": profit_factor,
            "sharpe": sharpe,
        }
