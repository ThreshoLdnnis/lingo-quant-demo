from __future__ import annotations

import asyncio
import gc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Protocol

import pandas as pd

from .partitioned_storage import PartitionedParquetStorage


def normalize_ticker(ticker: str) -> str:
    code = ticker.split(".")[0].zfill(6)
    suffix = "SH" if code.startswith(("60", "68", "90")) else "SZ"
    return f"{code}.{suffix}"


class MinuteBarProvider(Protocol):
    def __call__(self, ticker: str, start: str, end: str, period: str) -> pd.DataFrame:
        ...


def akshare_minute_provider(ticker: str, start: str, end: str, period: str = "1") -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise ImportError("Install AkShare with `pip install .[market]` before minute sync.") from exc

    pure_code = ticker.split(".")[0].zfill(6)
    return ak.stock_zh_a_hist_min_em(
        symbol=pure_code,
        start_date=start,
        end_date=end,
        period=period,
        adjust="qfq",
    )


@dataclass(frozen=True)
class AsyncFetchConfig:
    concurrency: int = 10
    max_retries: int = 3
    base_backoff_seconds: float = 2.0
    period: str = "1"
    failed_log_path: Path = Path("failed_tickers.log")


@dataclass
class FetchStats:
    submitted: int = 0
    succeeded: int = 0
    failed: int = 0
    empty: int = 0
    attempts: dict[str, int] = field(default_factory=dict)


class AsyncMinuteBarFetcher:
    """Producer-consumer minute-bar data pump with retry and non-blocking AkShare calls."""

    column_mapping = {
        "时间": "date",
        "日期": "date",
        "股票代码": "ticker",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }

    def __init__(
        self,
        storage: PartitionedParquetStorage,
        provider: MinuteBarProvider = akshare_minute_provider,
        config: AsyncFetchConfig | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.storage = storage
        self.provider = provider
        self.config = config or AsyncFetchConfig()
        self.sleep = sleep
        self.stats = FetchStats()
        self._failed_lock = asyncio.Lock()
        self._storage_lock = asyncio.Lock()

    async def fetch_many(self, tickers: Iterable[str], start: str, end: str) -> FetchStats:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        normalized = [normalize_ticker(ticker) for ticker in tickers]
        self.stats = FetchStats(submitted=len(normalized))

        producer = asyncio.create_task(self._produce(queue, normalized))
        consumers = [
            asyncio.create_task(self._consume(worker_id, queue, start, end))
            for worker_id in range(max(1, self.config.concurrency))
        ]

        await producer
        await queue.join()

        for _ in consumers:
            await queue.put(None)
        await asyncio.gather(*consumers)
        return self.stats

    async def _produce(self, queue: asyncio.Queue[str | None], tickers: list[str]) -> None:
        for ticker in tickers:
            await queue.put(ticker)

    async def _consume(self, worker_id: int, queue: asyncio.Queue[str | None], start: str, end: str) -> None:
        while True:
            ticker = await queue.get()
            try:
                if ticker is None:
                    return
                await self._fetch_clean_store(ticker, start, end)
            finally:
                queue.task_done()

    async def _fetch_clean_store(self, ticker: str, start: str, end: str) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            self.stats.attempts[ticker] = attempt
            try:
                raw = await asyncio.to_thread(self.provider, ticker, start, end, self.config.period)
                df = self.clean_minute_frame(raw, ticker)
                if df.empty:
                    self.stats.empty += 1
                else:
                    async with self._storage_lock:
                        await asyncio.to_thread(self.storage.save_minute_bars, df)
                    self.stats.succeeded += 1
                del raw
                del df
                gc.collect()
                return
            except Exception as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    await self.sleep(self.config.base_backoff_seconds * (2 ** (attempt - 1)))

        self.stats.failed += 1
        await self._record_failure(ticker, last_error)

    async def _record_failure(self, ticker: str, error: Exception | None) -> None:
        async with self._failed_lock:
            path = self.config.failed_log_path
            path.parent.mkdir(parents=True, exist_ok=True)
            message = f"{ticker}\t{type(error).__name__ if error else 'UnknownError'}\t{error or ''}\n"
            await asyncio.to_thread(self._append_text, path, message)

    @staticmethod
    def _append_text(path: Path, message: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message)

    def clean_minute_frame(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "ticker", "open", "high", "low", "close", "volume", "amount"])

        data = df.copy()
        rename = {col: self.column_mapping[col] for col in data.columns if col in self.column_mapping}
        data = data.rename(columns=rename)

        missing_ohlcv = {"date", "open", "high", "low", "close", "volume"} - set(data.columns)
        if missing_ohlcv:
            raise ValueError(f"Minute data missing required columns for {ticker}: {sorted(missing_ohlcv)}")

        if "amount" not in data.columns:
            data["amount"] = data["close"] * data["volume"]
        data["ticker"] = normalize_ticker(ticker)
        data["date"] = pd.to_datetime(data["date"])

        keep = ["date", "ticker", "open", "high", "low", "close", "volume", "amount"]
        data = data[keep]
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        data[numeric_cols] = data[numeric_cols].apply(pd.to_numeric, errors="coerce")
        return data.dropna(subset=keep).sort_values(["date", "ticker"]).reset_index(drop=True)
