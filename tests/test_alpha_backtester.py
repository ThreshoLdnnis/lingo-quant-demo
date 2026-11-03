import pandas as pd

from lingyu_quant import AlphaEngine, BacktestConfig, MockDataFetcher, VectorizedBacktester


def test_alpha_engine_outputs_cross_sectional_zscores():
    panel = MockDataFetcher(seed=1).fetch_daily_bars(["000001.SZ", "000002.SZ", "600000.SH"], "2025-01-01", "2025-03-31")
    alpha = AlphaEngine(panel).calc_vol_weighted_reversal(price_window=3, vol_window=5)
    latest = alpha.dropna().index.get_level_values("date").max()
    cross_section = alpha.xs(latest, level="date")["alpha_norm"].dropna()
    assert len(cross_section) == 3
    assert abs(cross_section.mean()) < 1e-7


def test_backtester_shifts_positions_and_reports_metrics():
    panel = MockDataFetcher(seed=2).fetch_daily_bars(["000001.SZ", "000002.SZ", "600000.SH"], "2025-01-01", "2025-04-30")
    alpha = AlphaEngine(panel).calc_vol_weighted_reversal(price_window=3, vol_window=5)
    merged = pd.merge(panel[["close"]], alpha[["alpha_norm"]], left_index=True, right_index=True)
    results = VectorizedBacktester(merged, BacktestConfig(top_n=2, fee_rate=0.001)).run_backtest()
    assert {"Gross_Return", "Net_Return", "Turnover", "Cumulative_Net"}.issubset(results.columns)
    assert results.iloc[0]["Turnover"] == 0
    assert "sharpe" in results.attrs["metrics"]
