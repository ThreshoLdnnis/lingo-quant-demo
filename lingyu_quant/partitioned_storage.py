from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd


class PartitionedParquetStorage:
    """Hive-style Parquet storage for A-share minute bars."""

    required_columns = {"date", "ticker", "open", "high", "low", "close", "volume", "amount"}

    def __init__(
        self,
        base_dir: str | Path = "./data/storage",
        market: str = "A",
        table_name: str = "min_bars",
    ) -> None:
        self.base_dir = Path(base_dir)
        self.market = market
        self.table_name = table_name
        self.root = self.base_dir / table_name / f"market={market}"
        self.root.mkdir(parents=True, exist_ok=True)

    def partition_dir(self, year: int, month: int) -> Path:
        return self.root / f"year={year:04d}" / f"month={month:02d}"

    def partition_file(self, year: int, month: int) -> Path:
        return self.partition_dir(year, month) / f"{self.table_name}.parquet"

    def save_minute_bars(self, df: pd.DataFrame) -> list[Path]:
        if df.empty:
            return []
        data = self._normalize_frame(df)
        written: list[Path] = []

        for (year, month), part in data.groupby([data["date"].dt.year, data["date"].dt.month], sort=True):
            target_dir = self.partition_dir(int(year), int(month))
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = self.partition_file(int(year), int(month))
            merged = pd.concat([pd.read_parquet(target_file, engine="pyarrow"), part], ignore_index=True) if target_file.exists() else part.copy()
            merged = self._dedupe_sort(merged)
            merged.to_parquet(target_file, engine="pyarrow", compression="snappy", index=False)
            written.append(target_file)
            del merged

        del data
        return written

    def load_minute_bars(
        self,
        tickers: Sequence[str] | None = None,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        filters = []
        if tickers:
            filters.append(("ticker", "in", list(tickers)))
        if start:
            filters.append(("date", ">=", pd.Timestamp(start)))
        if end:
            filters.append(("date", "<=", pd.Timestamp(end)))

        files = sorted(self.root.glob("year=*/month=*/*.parquet"))
        if not files:
            return pd.DataFrame(columns=["date", "ticker", "open", "high", "low", "close", "volume", "amount"])
        frames = [pd.read_parquet(path, engine="pyarrow", filters=filters or None) for path in files]
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return pd.DataFrame(columns=["date", "ticker", "open", "high", "low", "close", "volume", "amount"])
        return self._dedupe_sort(pd.concat(frames, ignore_index=True))

    def _normalize_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        data = df.reset_index() if list(df.index.names) == ["date", "ticker"] else df.copy()
        missing = self.required_columns - set(data.columns)
        if missing:
            raise ValueError(f"Minute bar frame missing columns: {sorted(missing)}")
        data = data[["date", "ticker", "open", "high", "low", "close", "volume", "amount"]].copy()
        data["date"] = pd.to_datetime(data["date"])
        data["ticker"] = data["ticker"].astype(str)
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        data[numeric_cols] = data[numeric_cols].apply(pd.to_numeric, errors="coerce")
        data = data.dropna(subset=["date", "ticker", *numeric_cols])
        return self._dedupe_sort(data)

    @staticmethod
    def _dedupe_sort(df: pd.DataFrame) -> pd.DataFrame:
        return (
            df.drop_duplicates(subset=["date", "ticker"], keep="last")
            .sort_values(["date", "ticker"])
            .reset_index(drop=True)
        )
