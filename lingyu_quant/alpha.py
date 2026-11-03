from __future__ import annotations

import numpy as np
import pandas as pd


class AlphaEngine:
    """Vectorized alpha generation engine for A-share panel data."""

    required_columns = {"close", "volume"}

    def __init__(self, data: pd.DataFrame) -> None:
        missing = self.required_columns - set(data.columns)
        if missing:
            raise ValueError(f"AlphaEngine missing required columns: {sorted(missing)}")
        if list(data.index.names) != ["date", "ticker"]:
            raise ValueError("AlphaEngine expects a MultiIndex named ['date', 'ticker'].")
        self.data = data.sort_index(level=["ticker", "date"])

    def calc_vol_weighted_reversal(
        self,
        price_window: int = 5,
        vol_window: int = 20,
        winsor_limit: float = 5.0,
    ) -> pd.DataFrame:
        if price_window < 2 or vol_window < 2:
            raise ValueError("Rolling windows must be >= 2.")

        df = self.data.copy()
        grouped = df.groupby(level="ticker", sort=False)
        close_sma = grouped["close"].transform(lambda x: x.rolling(price_window, min_periods=price_window).mean())
        vol_sma = grouped["volume"].transform(lambda x: x.rolling(vol_window, min_periods=vol_window).mean())

        price_deviation = (df["close"] - close_sma) / close_sma
        volume_ratio = df["volume"] / vol_sma.replace(0, np.nan)
        alpha = -1.0 * price_deviation * volume_ratio
        df["alpha_reversal"] = alpha.replace([np.inf, -np.inf], np.nan)

        def zscore(x: pd.Series) -> pd.Series:
            clipped = x.clip(lower=x.quantile(0.01), upper=x.quantile(0.99))
            normalized = (clipped - clipped.mean()) / (clipped.std(ddof=0) + 1e-8)
            return normalized.clip(-winsor_limit, winsor_limit)

        df["alpha_norm"] = df.groupby(level="date", sort=False)["alpha_reversal"].transform(zscore)
        return df[["alpha_reversal", "alpha_norm"]]

    @staticmethod
    def factor_information_coefficient(panel: pd.DataFrame, horizon: int = 1) -> pd.Series:
        required = {"close", "alpha_norm"}
        missing = required - set(panel.columns)
        if missing:
            raise ValueError(f"IC calculation missing required columns: {sorted(missing)}")

        work = panel.sort_index(level=["ticker", "date"]).copy()
        work["future_ret"] = work.groupby(level="ticker")["close"].pct_change(horizon).shift(-horizon)
        return work.groupby(level="date").apply(lambda x: x["alpha_norm"].corr(x["future_ret"]))
