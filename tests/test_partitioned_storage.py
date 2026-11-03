import pandas as pd

from lingyu_quant.partitioned_storage import PartitionedParquetStorage


def test_partitioned_storage_writes_hive_year_month_and_merges(tmp_path):
    storage = PartitionedParquetStorage(tmp_path)
    first = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01 09:31", "2026-06-01 09:32"]),
            "ticker": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "close": [10.1, 10.2],
            "volume": [1000, 1100],
            "amount": [10100, 11220],
        }
    )
    second = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01 09:32", "2026-07-01 09:31"]),
            "ticker": ["000001.SZ", "000002.SZ"],
            "open": [10.5, 20.0],
            "high": [10.6, 20.2],
            "low": [10.4, 19.9],
            "close": [10.55, 20.1],
            "volume": [1200, 2200],
            "amount": [12660, 44220],
        }
    )

    storage.save_minute_bars(first)
    written = storage.save_minute_bars(second)

    assert (tmp_path / "min_bars" / "market=A" / "year=2026" / "month=06" / "min_bars.parquet").exists()
    assert (tmp_path / "min_bars" / "market=A" / "year=2026" / "month=07" / "min_bars.parquet").exists()
    assert len(written) == 2

    loaded = storage.load_minute_bars()
    assert len(loaded) == 3
    june_932 = loaded[(loaded["ticker"] == "000001.SZ") & (loaded["date"] == pd.Timestamp("2026-06-01 09:32"))]
    assert float(june_932.iloc[0]["close"]) == 10.55
