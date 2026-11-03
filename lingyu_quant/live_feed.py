"""Event-driven live Level-1 feed for Lingyu Quant."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable

import aiohttp
import pandas as pd


Callback = Callable[[Any], Awaitable[None] | None]


@dataclass(frozen=True)
class LiveFeedConfig:
    """Runtime settings for the HTTP polling live feed."""

    poll_interval: float = 3.0
    request_timeout: float = 2.0
    max_backoff: float = 30.0
    emit_empty_bars: bool = False


class LiveMarketFeed:
    """
    Lingyu event-driven Level-1 market feed.

    The feed polls Tencent quote snapshots, aggregates cumulative Level-1
    volume/amount into one-minute OHLCV bars in memory, and emits events:

    - ``tick``: raw parsed quote snapshots.
    - ``minute_bar_closed``: a DataFrame indexed by ``date, ticker``.
    - ``feed_error``: transient network or parsing failures.
    """

    def __init__(
        self,
        tickers: Iterable[str],
        config: LiveFeedConfig | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.tickers = [self._normalize_ticker(ticker) for ticker in tickers]
        if not self.tickers:
            raise ValueError("LiveMarketFeed requires at least one ticker.")

        self.config = config or LiveFeedConfig()
        self.now_provider = now_provider or datetime.now
        self.query_codes = [self._to_tencent_code(ticker) for ticker in self.tickers]
        self.api_url = f"http://qt.gtimg.cn/q={','.join(self.query_codes)}"

        self.callbacks: dict[str, list[Callback]] = defaultdict(list)
        self.is_running = False

        self.current_minute_bars: dict[str, dict[str, Any]] = {}
        self.last_minute: pd.Timestamp | None = None
        self.previous_totals: dict[str, tuple[int, float]] = {}

    def on(self, event_name: str, callback: Callback) -> None:
        """Register an event listener."""

        self.callbacks[event_name].append(callback)

    def off(self, event_name: str, callback: Callback) -> None:
        """Remove a previously registered event listener."""

        if callback in self.callbacks.get(event_name, []):
            self.callbacks[event_name].remove(callback)

    async def start(self) -> None:
        """Start the polling heartbeat until ``stop`` is called."""

        self.is_running = True
        consecutive_errors = 0
        print("[*] 翎语 Live Feed 已启动，正在建立 HTTP 轮询连接 (间隔 3s)...")

        async with aiohttp.ClientSession() as session:
            while self.is_running:
                snapshots = await self._fetch_snapshot(session)
                if snapshots:
                    consecutive_errors = 0
                    await self._aggregate_and_check_boundary(snapshots)
                    await self._emit("tick", snapshots)
                    await asyncio.sleep(self.config.poll_interval)
                    continue

                consecutive_errors += 1
                backoff = min(self.config.max_backoff, self.config.poll_interval * (2 ** min(consecutive_errors, 4)))
                await asyncio.sleep(backoff)

    async def stop(self) -> None:
        """Stop the heartbeat after the current polling cycle."""

        self.is_running = False

    async def _emit(self, event_name: str, data: Any) -> None:
        for callback in list(self.callbacks.get(event_name, [])):
            result = callback(data)
            if asyncio.iscoroutine(result):
                await result

    async def _fetch_snapshot(self, session: aiohttp.ClientSession) -> list[dict[str, Any]]:
        try:
            async with session.get(self.api_url, timeout=self.config.request_timeout) as response:
                response.raise_for_status()
                text = await response.text(encoding="gbk", errors="ignore")
                return self._parse_tencent_quote(text)
        except Exception as exc:  # noqa: BLE001 - daemon must survive transient feed failures.
            print(f"[-] 实时流网络异常: {exc}")
            await self._emit("feed_error", exc)
            return []

    def _parse_tencent_quote(self, raw_text: str) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []

        for line in raw_text.strip().split(";"):
            if not line or "=" not in line:
                continue
            left, right = line.split("=", 1)
            data_arr = right.strip().strip('"').split("~")
            tencent_code = left.replace("v_", "").strip()
            if len(data_arr) <= 37 or len(tencent_code) < 8:
                continue

            price = self._to_float(data_arr[3])
            volume_total = self._to_int(data_arr[36])
            amount_total = self._to_float(data_arr[37])
            if price is None or volume_total is None or amount_total is None:
                continue

            parsed.append(
                {
                    "ticker": self._from_tencent_code(tencent_code),
                    "price": price,
                    "volume_total": volume_total * 100,
                    "amount_total": amount_total * 10_000,
                    "quote_time": data_arr[30] if len(data_arr) > 30 else "",
                }
            )

        return parsed

    async def _aggregate_and_check_boundary(self, snapshots: list[dict[str, Any]]) -> None:
        now = pd.Timestamp(self.now_provider()).floor("min")

        if self.last_minute is not None and now != self.last_minute:
            closed = self._closed_bars_frame()
            if not closed.empty or self.config.emit_empty_bars:
                await self._emit("minute_bar_closed", closed)
            self.current_minute_bars.clear()

        self.last_minute = now

        for snapshot in snapshots:
            self._update_bar(now, snapshot)

    def _update_bar(self, minute: pd.Timestamp, snapshot: dict[str, Any]) -> None:
        ticker = snapshot["ticker"]
        price = float(snapshot["price"])
        volume_total = int(snapshot["volume_total"])
        amount_total = float(snapshot["amount_total"])

        prev_volume, prev_amount = self.previous_totals.get(ticker, (volume_total, amount_total))
        delta_volume = max(0, volume_total - prev_volume)
        delta_amount = max(0.0, amount_total - prev_amount)
        self.previous_totals[ticker] = (volume_total, amount_total)

        bar = self.current_minute_bars.get(ticker)
        if bar is None:
            self.current_minute_bars[ticker] = {
                "date": minute,
                "ticker": ticker,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": delta_volume,
                "amount": delta_amount,
                "snapshot_count": 1,
            }
            return

        bar["high"] = max(float(bar["high"]), price)
        bar["low"] = min(float(bar["low"]), price)
        bar["close"] = price
        bar["volume"] += delta_volume
        bar["amount"] += delta_amount
        bar["snapshot_count"] += 1

    def _closed_bars_frame(self) -> pd.DataFrame:
        if not self.current_minute_bars:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount", "snapshot_count"])

        frame = pd.DataFrame.from_records(list(self.current_minute_bars.values()))
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.set_index(["date", "ticker"]).sort_index()
        return frame[["open", "high", "low", "close", "volume", "amount", "snapshot_count"]]

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        code, sep, market = ticker.strip().upper().partition(".")
        if not sep or market not in {"SZ", "SH", "BJ"} or not code.isdigit() or len(code) != 6:
            raise ValueError(f"Invalid A-share ticker: {ticker!r}")
        return f"{code}.{market}"

    @staticmethod
    def _to_tencent_code(ticker: str) -> str:
        code, market = ticker.split(".")
        return f"{market.lower()}{code}"

    @staticmethod
    def _from_tencent_code(code: str) -> str:
        market = code[:2].upper()
        return f"{code[2:]}.{market}"

    @staticmethod
    def _to_float(value: str) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: str) -> int | None:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
