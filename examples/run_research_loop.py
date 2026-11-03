from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lingyu_quant import AlphaEngine, BacktestConfig, LocalParquetStorage, MockDataFetcher, VectorizedBacktester


def main() -> None:
    tickers = ["000408.SZ", "601069.SH", "600392.SH", "000975.SZ", "301500.SZ", "000001.SZ"]
    fetcher = MockDataFetcher(seed=42)
    storage = LocalParquetStorage()

    raw = fetcher.fetch_daily_bars(tickers, "2024-01-01", "2026-06-15")
    path = storage.save_market_data(raw, table_name="mock_a_share_daily")
    print(f"[+] saved market panel: {path}")

    panel = storage.load_market_data(
        table_name="mock_a_share_daily",
        tickers=["000408.SZ", "601069.SH", "600392.SH", "000975.SZ", "301500.SZ"],
        start_date="2025-01-01",
    )
    alpha = AlphaEngine(panel).calc_vol_weighted_reversal()
    merged = pd.merge(panel[["close"]], alpha[["alpha_norm"]], left_index=True, right_index=True)
    results = VectorizedBacktester(merged, BacktestConfig(top_n=3, fee_rate=0.003)).run_backtest()

    latest = alpha.index.get_level_values("date").max()
    print(f"\n[!] {latest.date()} alpha z-score")
    print(alpha.xs(latest, level="date")["alpha_norm"].sort_values(ascending=False))
    print("\n[!] performance")
    for key, value in results.attrs["metrics"].items():
        print(f"{key}: {value:.4f}")


if __name__ == "__main__":
    main()
