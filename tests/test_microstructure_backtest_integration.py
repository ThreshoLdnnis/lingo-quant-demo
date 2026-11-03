import numpy as np
import pandas as pd

from examples.run_microstructure_backtest import build_risk_panel, make_demo_minute_bars
from lingyu_quant.backtester import BacktestConfig, VectorizedBacktester
from lingyu_quant.microstructure_alpha import MicrostructureAlphaEngine
from lingyu_quant.risk import BarraStyleNeutralizer


def test_microstructure_signal_can_be_neutralized_and_backtested():
    min_panel = make_demo_minute_bars()
    alpha_daily = MicrostructureAlphaEngine(min_panel).extract_smart_money_factors()
    risk_panel = build_risk_panel(min_panel, alpha_daily)
    risk_panel["pure_smart_money_score"] = BarraStyleNeutralizer(risk_panel, alpha_col="alpha_raw").execute_neutralization()

    raw_panel = risk_panel[["close", "alpha_raw"]].rename(columns={"alpha_raw": "alpha_norm"})
    pure_panel = risk_panel[["close", "pure_smart_money_score"]].rename(columns={"pure_smart_money_score": "alpha_norm"})

    raw_res = VectorizedBacktester(raw_panel, BacktestConfig(top_n=3, fee_rate=0.003)).run_backtest()
    pure_res = VectorizedBacktester(pure_panel, BacktestConfig(top_n=3, fee_rate=0.003)).run_backtest()

    assert np.isfinite(raw_res.attrs["metrics"]["sharpe"])
    assert np.isfinite(pure_res.attrs["metrics"]["sharpe"])
    assert abs(risk_panel["pure_smart_money_score"].groupby(level="date").mean()).max() < 1e-8
    assert {"Gross_Return", "Net_Return", "Turnover", "Cumulative_Net"}.issubset(raw_res.columns)
