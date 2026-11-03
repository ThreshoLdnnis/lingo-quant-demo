from lingyu_quant import LocalParquetStorage, MockDataFetcher


def test_parquet_storage_round_trip(tmp_path):
    panel = MockDataFetcher(seed=3).fetch_daily_bars(["000001.SZ", "600000.SH"], "2025-01-01", "2025-01-31")
    storage = LocalParquetStorage(tmp_path)
    storage.save_market_data(panel, "daily")
    sliced = storage.load_market_data("daily", tickers=["000001.SZ"], start_date="2025-01-10")
    assert sliced.index.names == ["date", "ticker"]
    assert set(sliced.index.get_level_values("ticker")) == {"000001.SZ"}
    assert sliced.index.get_level_values("date").min().strftime("%Y-%m-%d") >= "2025-01-10"
