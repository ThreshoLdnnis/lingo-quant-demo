from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lingyu_quant.backtester import BacktestConfig, VectorizedBacktester
from lingyu_quant.microstructure_alpha import MicrostructureAlphaEngine
from lingyu_quant.partitioned_storage import PartitionedParquetStorage
from lingyu_quant.risk import BarraStyleNeutralizer


def make_demo_minute_bars() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    tickers = ["000408.SZ", "601069.SH", "600392.SH", "301500.SZ", "000975.SZ", "002230.SZ"]
    dates = pd.date_range("2026-05-25", periods=18, freq="B")
    intraday = pd.date_range("09:31", periods=32, freq="10min").time
    frames: list[pd.DataFrame] = []

    for day_idx, trade_date in enumerate(dates):
        for ticker_idx, ticker in enumerate(tickers):
            base = 8 + ticker_idx * 3.2 + day_idx * 0.03
            minutes = [pd.Timestamp.combine(trade_date.date(), t) for t in intraday]
            scenario_bias = ticker_idx % 3
            noise = rng.normal(0, 0.006, len(minutes))
            if scenario_bias == 0:
                volume = rng.normal(5200, 350, len(minutes)).clip(1000)
                drift = np.linspace(-0.012, 0.008, len(minutes))
            elif scenario_bias == 1:
                volume = rng.normal(1200, 250, len(minutes)).clip(200)
                volume[:3] *= 8
                drift = np.r_[np.linspace(0.015, 0.04, 3), np.linspace(0.02, -0.012, len(minutes) - 3)]
            else:
                volume = rng.normal(1800, 280, len(minutes)).clip(300)
                volume[8:16] *= 3.5
                drift = np.linspace(-0.018, 0.002, len(minutes))

            close = base * (1 + drift + np.cumsum(noise) * 0.08)
            open_ = np.r_[close[0], close[:-1]]
            high = np.maximum(open_, close) * (1 + rng.random(len(minutes)) * 0.004)
            low = np.minimum(open_, close) * (1 - rng.random(len(minutes)) * 0.004)
            amount = close * volume
            frames.append(
                pd.DataFrame(
                    {
                        "date": minutes,
                        "ticker": ticker,
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                        "amount": amount,
                    }
                )
            )

    return pd.concat(frames, ignore_index=True)


def load_or_seed_minute_data(storage: PartitionedParquetStorage) -> pd.DataFrame:
    min_panel = storage.load_minute_bars()
    if not min_panel.empty:
        return min_panel

    print("[!] 未发现分钟线分区数据，生成模拟测试池用于全链路验收。")
    demo = make_demo_minute_bars()
    storage.save_minute_bars(demo)
    return storage.load_minute_bars()


def build_risk_panel(min_panel: pd.DataFrame, alpha_daily: pd.DataFrame) -> pd.DataFrame:
    work = min_panel.copy()
    work["trade_date"] = pd.to_datetime(work["date"]).dt.normalize()
    daily_close = work.sort_values("date").groupby(["trade_date", "ticker"])["close"].last()
    daily_close.index = daily_close.index.set_names(["date", "ticker"])

    risk_panel = alpha_daily[["smart_money_score"]].rename(columns={"smart_money_score": "alpha_raw"}).join(
        daily_close.rename("close"),
        how="inner",
    )

    tickers = risk_panel.index.get_level_values("ticker")
    ticker_codes = pd.Series(tickers, index=risk_panel.index).str.slice(0, 6).astype(int)
    risk_panel["log_market_cap"] = np.log((risk_panel["close"] * (1_000_000 + ticker_codes * 90)).clip(lower=1))
    risk_panel["industry_code"] = (ticker_codes % 5 + 1).astype(str)
    return risk_panel.dropna(subset=["alpha_raw", "close", "log_market_cap", "industry_code"])


def summarize(label: str, results: pd.DataFrame) -> None:
    metrics = results.attrs.get("metrics", {})
    print(f"\n[{label}]")
    print(f"年化收益率: {metrics.get('annualized_return', float('nan')):.2%}")
    print(f"年化波动率: {metrics.get('annualized_vol', float('nan')):.2%}")
    print(f"夏普比率:   {metrics.get('sharpe', float('nan')):.2f}")
    print(f"最大回撤:   {metrics.get('max_drawdown', float('nan')):.2%}")
    print(f"日均换手:   {metrics.get('avg_turnover', float('nan')):.2%}")
    print(f"总摩擦损耗: {metrics.get('total_cost', float('nan')):.4f}")


def main() -> None:
    print("[*] 正在启动 翎语系统 1.5 - 高频多因子全链路风险回测管线...")

    storage = PartitionedParquetStorage()
    min_panel = load_or_seed_minute_data(storage)

    alpha_daily = MicrostructureAlphaEngine(min_panel).extract_smart_money_factors()
    risk_panel = build_risk_panel(min_panel, alpha_daily)

    neutralizer = BarraStyleNeutralizer(risk_panel, alpha_col="alpha_raw")
    risk_panel["pure_smart_money_score"] = neutralizer.execute_neutralization()

    raw_test_panel = risk_panel[["close", "alpha_raw"]].rename(columns={"alpha_raw": "alpha_norm"})
    pure_test_panel = risk_panel[["close", "pure_smart_money_score"]].rename(
        columns={"pure_smart_money_score": "alpha_norm"}
    )

    print("\n[*] 运行双轨回测对比...")
    config = BacktestConfig(top_n=3, fee_rate=0.003)
    raw_res = VectorizedBacktester(raw_test_panel, config).run_backtest()
    pure_res = VectorizedBacktester(pure_test_panel, config).run_backtest()

    summarize("Raw Smart Money Signal", raw_res)
    summarize("Barra-Neutral Pure Signal", pure_res)
    print("\n[+] 翎语系统：全链路贯通回测完成。")


if __name__ == "__main__":
    main()
