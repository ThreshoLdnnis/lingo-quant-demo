import asyncio

import pandas as pd

from lingyu_quant.async_fetcher import AsyncFetchConfig, AsyncMinuteBarFetcher
from lingyu_quant.partitioned_storage import PartitionedParquetStorage


def minute_frame():
    return pd.DataFrame(
        {
            "时间": ["2026-06-01 09:31:00", "2026-06-01 09:32:00"],
            "开盘": [10.0, 10.1],
            "最高": [10.2, 10.3],
            "最低": [9.9, 10.0],
            "收盘": [10.1, 10.2],
            "成交量": [1000, 1200],
            "成交额": [10100, 12240],
        }
    )


def test_async_fetcher_cleans_and_stores_minute_bars(tmp_path):
    storage = PartitionedParquetStorage(tmp_path)

    def provider(ticker, start, end, period):
        return minute_frame()

    fetcher = AsyncMinuteBarFetcher(
        storage,
        provider=provider,
        config=AsyncFetchConfig(concurrency=2, failed_log_path=tmp_path / "failed.log"),
    )

    stats = asyncio.run(fetcher.fetch_many(["000001.SZ", "600000.SH"], "2026-06-01 09:30:00", "2026-06-01 15:00:00"))

    assert stats.submitted == 2
    assert stats.succeeded == 2
    assert stats.failed == 0
    loaded = storage.load_minute_bars()
    assert set(loaded["ticker"]) == {"000001.SZ", "600000.SH"}


def test_async_fetcher_retries_and_records_failed_ticker(tmp_path):
    storage = PartitionedParquetStorage(tmp_path)
    sleeps = []
    calls = {"count": 0}

    def provider(ticker, start, end, period):
        calls["count"] += 1
        raise TimeoutError("network down")

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    fetcher = AsyncMinuteBarFetcher(
        storage,
        provider=provider,
        config=AsyncFetchConfig(
            concurrency=1,
            max_retries=3,
            base_backoff_seconds=2,
            failed_log_path=tmp_path / "failed_tickers.log",
        ),
        sleep=fake_sleep,
    )

    stats = asyncio.run(fetcher.fetch_many(["000001.SZ"], "2026-06-01 09:30:00", "2026-06-01 15:00:00"))

    assert calls["count"] == 3
    assert sleeps == [2, 4]
    assert stats.failed == 1
    assert "000001.SZ" in (tmp_path / "failed_tickers.log").read_text()
