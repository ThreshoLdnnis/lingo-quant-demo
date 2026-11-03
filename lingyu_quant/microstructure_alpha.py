from __future__ import annotations

import numpy as np
import pandas as pd


class MicrostructureAlphaEngine:
    """Extract daily smart-money footprints from A-share minute bars."""

    required_columns = {"date", "ticker", "open", "high", "low", "close", "volume", "amount"}

    def __init__(self, min_data: pd.DataFrame, eps: float = 1e-8) -> None:
        data = min_data.reset_index() if list(min_data.index.names) == ["date", "ticker"] else min_data.copy()
        if "datetime" in data.columns and "date" not in data.columns:
            data = data.rename(columns={"datetime": "date"})

        missing = self.required_columns - set(data.columns)
        if missing:
            raise ValueError(f"Microstructure data missing columns: {sorted(missing)}")

        self.eps = eps
        self.data = self._prepare(data)

    def extract_smart_money_factors(self) -> pd.DataFrame:
        """Compress minute bars to daily cross-sectional microstructure factors."""
        df = self.data.copy()
        grouped = df.groupby(["trade_date", "ticker"], sort=False)
        total_volume = grouped["volume"].sum()

        vwap = grouped["amount"].sum() / (total_volume + self.eps)
        twap = grouped["close"].mean()
        vwap_accumulation = (twap - vwap) / (vwap + self.eps)

        pulse_penalty = grouped["volume"].max() / (grouped["volume"].mean() + self.eps)

        downside_volume = df["volume"].where(df["ret_1m"] < 0, 0.0).groupby(
            [df["trade_date"], df["ticker"]], sort=False
        ).sum()
        downside_support = downside_volume / (total_volume + self.eps)

        minute_volume_share = df["volume"] / (grouped["volume"].transform("sum") + self.eps)
        entropy_terms = -(minute_volume_share.where(minute_volume_share > 0, 1.0) * np.log(
            minute_volume_share.where(minute_volume_share > 0, 1.0)
        ))
        volume_entropy = entropy_terms.groupby([df["trade_date"], df["ticker"]], sort=False).sum()

        pre_close_volume = df["volume"].where(df["time"] >= pd.Timestamp("14:30:00").time(), 0.0).groupby(
            [df["trade_date"], df["ticker"]], sort=False
        ).sum()
        pre_close_strength = pre_close_volume / (total_volume + self.eps)

        factors = pd.DataFrame(
            {
                "vwap_accumulation": vwap_accumulation,
                "pulse_penalty": pulse_penalty,
                "downside_support": downside_support,
                "volume_entropy": volume_entropy,
                "pre_close_strength": pre_close_strength,
            }
        ).fillna(0.0)
        factors.index = factors.index.set_names(["date", "ticker"])

        raw_score = (
            -factors["vwap_accumulation"]
            + factors["downside_support"]
            + 0.5 * factors["volume_entropy"]
            + factors["pre_close_strength"]
            - 0.1 * factors["pulse_penalty"]
        )
        factors["smart_money_raw"] = raw_score
        factors["smart_money_score"] = raw_score.groupby(level="date", sort=False).transform(self._zscore)
        return factors

    def _prepare(self, data: pd.DataFrame) -> pd.DataFrame:
        out = data[list(self.required_columns)].copy()
        out["date"] = pd.to_datetime(out["date"])
        out["trade_date"] = out["date"].dt.normalize()
        out["time"] = out["date"].dt.time
        out["ticker"] = out["ticker"].astype(str)
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        out[numeric_cols] = out[numeric_cols].apply(pd.to_numeric, errors="coerce")
        out = out.dropna(subset=["date", "ticker", *numeric_cols])
        out = out.sort_values(["trade_date", "ticker", "date"])
        out["ret_1m"] = out.groupby(["trade_date", "ticker"], sort=False)["close"].pct_change().fillna(0.0)
        return out

    def _zscore(self, values: pd.Series) -> pd.Series:
        return (values - values.mean()) / (values.std(ddof=0) + self.eps)
