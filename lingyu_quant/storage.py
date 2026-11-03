from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd


class LocalParquetStorage:
    """Local Parquet lakehouse with ticker/date predicate pushdown."""

    def __init__(self, base_dir: str | Path = "./data/storage") -> None:
        self.base_dir = Path(base_dir)
        self.daily_path = self.base_dir / "daily_bars" / "market=A"
        self.daily_path.mkdir(parents=True, exist_ok=True)

    def table_path(self, table_name: str) -> Path:
        return self.daily_path / f"{table_name}.parquet"

    def save_market_data(self, df: pd.DataFrame, table_name: str = "a_share_daily") -> Path:
        if list(df.index.names) == ["date", "ticker"]:
            output = df.reset_index()
        else:
            output = df.copy()

        required = {"date", "ticker", "close", "volume"}
        missing = required - set(output.columns)
        if missing:
            raise ValueError(f"Parquet save missing required columns: {sorted(missing)}")

        output["date"] = pd.to_datetime(output["date"])
        target = self.table_path(table_name)
        output.sort_values(["date", "ticker"]).to_parquet(
            target,
            engine="pyarrow",
            compression="snappy",
            index=False,
        )
        return target

    def load_market_data(
        self,
        table_name: str = "a_share_daily",
        tickers: Sequence[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        target = self.table_path(table_name)
        if not target.exists():
            raise FileNotFoundError(f"Market data table not found: {target}")

        filters = []
        if tickers:
            filters.append(("ticker", "in", list(tickers)))
        if start_date:
            filters.append(("date", ">=", pd.Timestamp(start_date)))
        if end_date:
            filters.append(("date", "<=", pd.Timestamp(end_date)))

        df = pd.read_parquet(target, engine="pyarrow", filters=filters or None)
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"]).set_index(
                pd.MultiIndex.from_arrays([[], []], names=["date", "ticker"])
            )
        return df.set_index(["date", "ticker"]).sort_index()
