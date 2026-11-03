from __future__ import annotations

import numpy as np
import pandas as pd


def exposure_by_bucket(weights: pd.Series, metadata: pd.DataFrame, bucket_col: str) -> pd.Series:
    """Aggregate portfolio weights by industry, style, or any metadata bucket."""
    if weights.index.name != "ticker":
        weights = weights.rename_axis("ticker")
    joined = weights.rename("weight").to_frame().join(metadata[[bucket_col]], how="left")
    return joined.groupby(bucket_col)["weight"].sum().sort_values(ascending=False)


def cap_bucket_exposure(weights: pd.Series, metadata: pd.DataFrame, bucket_col: str, limit: float) -> pd.Series:
    """Simple bucket exposure cap for MVP risk control before a full Barra model is connected."""
    if limit <= 0:
        raise ValueError("limit must be positive.")
    weights = weights.copy()
    exposures = exposure_by_bucket(weights, metadata, bucket_col)
    for bucket, exposure in exposures.items():
        if exposure > limit:
            tickers = metadata.index[metadata[bucket_col] == bucket]
            weights.loc[weights.index.intersection(tickers)] *= limit / exposure
    return weights / weights.sum()


class BarraStyleNeutralizer:
    """Cross-sectional Barra-lite neutralizer for A-share alpha signals.

    The model removes market-cap and industry effects from an alpha column by
    running a daily cross-sectional least-squares regression:

        alpha = intercept + beta_size * log_market_cap + industry_dummies + residual

    The residual is then z-scored by date and returned as a pure alpha signal.
    """

    required_columns = {"log_market_cap", "industry_code"}

    def __init__(
        self,
        panel: pd.DataFrame,
        alpha_col: str = "alpha_raw",
        size_col: str = "log_market_cap",
        industry_col: str = "industry_code",
        eps: float = 1e-8,
    ) -> None:
        missing = {alpha_col, size_col, industry_col} - set(panel.columns)
        if missing:
            raise ValueError(f"Neutralizer missing columns: {sorted(missing)}")
        if list(panel.index.names) != ["date", "ticker"]:
            raise ValueError("BarraStyleNeutralizer expects MultiIndex ['date', 'ticker'].")

        self.panel = panel.copy()
        self.alpha_col = alpha_col
        self.size_col = size_col
        self.industry_col = industry_col
        self.eps = eps

    def execute_neutralization(self) -> pd.Series:
        residual = pd.concat(
            [self._neutralize_one_date(frame) for _, frame in self.panel.groupby(level="date", sort=False)]
        ).sort_index()
        residual.name = "pure_smart_money_score"
        return residual.groupby(level="date", group_keys=False).transform(self._zscore)

    def _neutralize_one_date(self, frame: pd.DataFrame) -> pd.Series:
        y = pd.to_numeric(frame[self.alpha_col], errors="coerce")
        size = pd.to_numeric(frame[self.size_col], errors="coerce")
        industries = frame[self.industry_col].astype(str)

        valid = y.notna() & size.notna() & industries.notna()
        output = pd.Series(np.nan, index=frame.index, dtype=float)
        if valid.sum() < 3:
            output.loc[valid] = y.loc[valid] - y.loc[valid].mean()
            return output.fillna(0.0)

        x_size = self._zscore(size.loc[valid])
        industry_dummies = pd.get_dummies(industries.loc[valid], prefix="ind", drop_first=True, dtype=float)
        design = pd.concat(
            [
                pd.Series(1.0, index=x_size.index, name="intercept"),
                x_size.rename("size"),
                industry_dummies,
            ],
            axis=1,
        )
        coefficients = np.linalg.pinv(design.to_numpy(dtype=float)) @ y.loc[valid].to_numpy(dtype=float)
        fitted = design.to_numpy(dtype=float) @ coefficients
        output.loc[valid] = y.loc[valid].to_numpy(dtype=float) - fitted
        return output.fillna(0.0)

    def _zscore(self, values: pd.Series) -> pd.Series:
        return (values - values.mean()) / (values.std(ddof=0) + self.eps)
