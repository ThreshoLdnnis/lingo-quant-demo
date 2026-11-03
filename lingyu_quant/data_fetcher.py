from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from tqdm import tqdm


def normalize_ticker(ticker: str) -> str:
    code = ticker.split(".")[0].zfill(6)
    suffix = "SH" if code.startswith(("60", "68", "90")) else "SZ"
    return f"{code}.{suffix}"


@dataclass(frozen=True)
class MockDataFetcher:
    """Deterministic A-share-like panel data generator for local research loops."""

    source: str = "mock_local"
    seed: int = 7

    def fetch_daily_bars(
        self,
        tickers: Sequence[str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(self.seed)
        dates = pd.date_range(start=start_date, end=end_date, freq="B")
        normalized = [normalize_ticker(ticker) for ticker in tickers]
        index = pd.MultiIndex.from_product([dates, normalized], names=["date", "ticker"])
        n_dates = len(dates)
        frames: list[pd.DataFrame] = []

        for ticker in normalized:
            drift = rng.normal(0.00025, 0.00015)
            shocks = rng.normal(drift, 0.019, size=n_dates)
            close = 10.0 * np.exp(np.cumsum(shocks))
            open_ = close * (1 + rng.normal(0, 0.006, size=n_dates))
            high = np.maximum(open_, close) * (1 + rng.random(n_dates) * 0.018)
            low = np.minimum(open_, close) * (1 - rng.random(n_dates) * 0.018)
            base_volume = rng.lognormal(mean=15.2, sigma=0.5, size=n_dates)
            volume = base_volume * (1 + np.abs(shocks) * 18)
            amount = volume * close

            frames.append(
                pd.DataFrame(
                    {
                        "date": dates,
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

        panel = pd.concat(frames, ignore_index=True)
        panel = panel.set_index(["date", "ticker"]).reindex(index).sort_index()
        return panel


class AkShareFetcher:
    """Production-oriented AkShare adapter with field normalization and rate limiting."""

    column_mapping = {
        "日期": "date",
        "股票代码": "ticker",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }

    def __init__(self, adjust: str = "qfq") -> None:
        self.adjust = adjust

    @staticmethod
    def _clean_ticker(ticker: str) -> str:
        return ticker.split(".")[0].zfill(6)

    def fetch_single_stock_daily(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError as exc:
            raise ImportError("Install AkShare with `pip install .[market]` before using AkShareFetcher.") from exc

        pure_code = self._clean_ticker(ticker)
        try:
            raw = ak.stock_zh_a_hist(
                symbol=pure_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=self.adjust,
            )
        except Exception as exc:
            print(f"[-] fetch failed for {ticker}: {exc}")
            return pd.DataFrame()

        if raw.empty:
            return pd.DataFrame()

        missing = set(self.column_mapping) - set(raw.columns)
        if missing:
            raise ValueError(f"AkShare response missing columns for {ticker}: {sorted(missing)}")

        df = raw[list(self.column_mapping)].rename(columns=self.column_mapping)
        df["date"] = pd.to_datetime(df["date"])
        df["ticker"] = normalize_ticker(pure_code)
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
        return df.dropna(subset=["date", "ticker", "close", "volume"])

    def fetch_batch_daily(
        self,
        tickers: Iterable[str],
        start_date: str,
        end_date: str,
        delay: float = 0.25,
    ) -> pd.DataFrame:
        tickers = list(tickers)
        frames: list[pd.DataFrame] = []
        for ticker in tqdm(tickers, desc="Lingyu market sync"):
            frame = self.fetch_single_stock_daily(ticker, start_date, end_date)
            if not frame.empty:
                frames.append(frame)
            if delay > 0:
                time.sleep(delay)

        if not frames:
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True).set_index(["date", "ticker"]).sort_index()
