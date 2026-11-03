from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    top_n: int = 10
    fee_rate: float = 0.003
    max_weight: float = 0.12


class VectorizedBacktester:
    """Vectorized cross-sectional Top-N long backtester with T+1 alignment."""

    def __init__(self, data_panel: pd.DataFrame, config: BacktestConfig | None = None) -> None:
        required = {"close", "alpha_norm"}
        missing = required - set(data_panel.columns)
        if missing:
            raise ValueError(f"Backtester missing required columns: {sorted(missing)}")
        if list(data_panel.index.names) != ["date", "ticker"]:
            raise ValueError("VectorizedBacktester expects MultiIndex ['date', 'ticker'].")
        self.data = data_panel.sort_index(level=["ticker", "date"]).copy()
        self.config = config or BacktestConfig()

    def run_backtest(self) -> pd.DataFrame:
        if self.config.top_n <= 0:
            raise ValueError("top_n must be positive.")

        work = self.data.copy()
        work["ret"] = work.groupby(level="ticker")["close"].pct_change()
        alpha_wide = work["alpha_norm"].unstack("ticker")
        ret_wide = work["ret"].unstack("ticker").fillna(0.0)

        ranks = alpha_wide.rank(axis=1, ascending=False, method="first", na_option="bottom")
        target_weights = (ranks <= self.config.top_n).astype(float)
        target_weights = target_weights.div(target_weights.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
        target_weights = target_weights.clip(upper=self.config.max_weight)
        target_weights = target_weights.div(target_weights.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

        actual_positions = target_weights.shift(1).fillna(0.0)
        turnover = actual_positions.diff().abs().sum(axis=1).fillna(actual_positions.abs().sum(axis=1))
        gross_returns = (actual_positions * ret_wide).sum(axis=1)
        costs = turnover * self.config.fee_rate
        net_returns = gross_returns - costs

        results = pd.DataFrame(
            {
                "Gross_Return": gross_returns,
                "Net_Return": net_returns,
                "Turnover": turnover,
                "Cost": costs,
            }
        )
        results["Cumulative_Gross"] = (1 + results["Gross_Return"]).cumprod()
        results["Cumulative_Net"] = (1 + results["Net_Return"]).cumprod()
        results.attrs["metrics"] = self.performance_metrics(results)
        return results

    @staticmethod
    def performance_metrics(results: pd.DataFrame) -> dict[str, float]:
        net = results["Net_Return"].fillna(0.0)
        annualized_return = float(net.mean() * 252)
        annualized_vol = float(net.std(ddof=0) * np.sqrt(252))
        rolling_max = results["Cumulative_Net"].cummax()
        drawdown = (results["Cumulative_Net"] - rolling_max) / rolling_max.replace(0, np.nan)
        return {
            "annualized_return": annualized_return,
            "annualized_vol": annualized_vol,
            "sharpe": float(annualized_return / (annualized_vol + 1e-8)),
            "max_drawdown": float(drawdown.min()),
            "avg_turnover": float(results["Turnover"].mean()),
            "total_cost": float(results["Cost"].sum()),
        }
