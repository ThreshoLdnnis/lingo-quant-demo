"""Non-linear alpha prediction engine for Lingyu Quant."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Iterable

import numpy as np
import pandas as pd


EPS = 1e-8


@dataclass(frozen=True)
class LightGBMConfig:
    """Conservative tree settings for noisy A-share cross-sectional alpha."""

    n_estimators: int = 150
    max_depth: int = 5
    learning_rate: float = 0.05
    random_state: int = 42
    n_jobs: int = -1


class NonLinearAlphaPredictor:
    """
    Lingyu non-linear alpha engine.

    The model learns interactions among purified factors and predicts T+2
    cross-sectional return ranks, not absolute returns. This keeps the target
    focused on relative alpha rather than broad market direction.
    """

    def __init__(self, n_estimators: int = 150, max_depth: int = 5, learning_rate: float = 0.05):
        self.config = LightGBMConfig(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
        )
        self.model = self._build_model()
        self.feature_names_: list[str] | None = None

    def align_features_and_labels(self, features: pd.DataFrame, close_prices: pd.Series):
        """
        Align T-day features with T+2 forward cross-sectional return ranks.

        Parameters
        ----------
        features:
            Factor matrix indexed by ``(date, ticker)``.
        close_prices:
            Close price series indexed by the same ``(date, ticker)`` panel.
        """

        self._require_panel_index(features, "features")
        self._require_panel_index(close_prices, "close_prices")

        features = features.sort_index()
        close_prices = close_prices.sort_index().astype(float)

        fwd_ret = close_prices.groupby(level="ticker").shift(-2) / close_prices - 1.0
        labels = fwd_ret.groupby(level="date").transform(lambda x: x.rank(pct=True) * 2.0 - 1.0)

        dataset = features.copy()
        dataset["label"] = labels.reindex(dataset.index)
        dataset = dataset.replace([np.inf, -np.inf], np.nan).dropna()

        return dataset.drop(columns=["label"]), dataset["label"]

    def train_and_predict(self, X_train: pd.DataFrame, y_train: pd.Series, X_pred: pd.DataFrame) -> pd.Series:
        """Train LightGBM and return cross-sectionally normalized alpha scores."""

        self._require_panel_index(X_train, "X_train")
        self._require_panel_index(X_pred, "X_pred")

        feature_names = list(X_train.columns)
        if not feature_names:
            raise ValueError("X_train must contain at least one feature column")
        if list(X_pred.columns) != feature_names:
            X_pred = X_pred.reindex(columns=feature_names)
        if X_pred.isna().any().any():
            raise ValueError("X_pred is missing one or more training feature columns")

        print(f"[*] 正在训练 LightGBM 非线性引擎，样本切片量: {len(X_train)} 行...")
        self.model.fit(X_train.to_numpy(), y_train.to_numpy())
        self.feature_names_ = feature_names

        preds = self.model.predict(X_pred.to_numpy())
        alpha_pred = pd.Series(preds, index=X_pred.index, name="ml_alpha_raw")

        alpha_norm = alpha_pred.groupby(level="date").transform(self._zscore)
        alpha_norm.name = "ml_alpha_norm"
        return alpha_norm

    def get_feature_importance(self, feature_names: Iterable[str] | None = None) -> pd.Series:
        """Return model feature importance sorted descending."""

        if feature_names is None:
            if self.feature_names_ is None:
                raise ValueError("feature_names must be provided before the model has been trained")
            feature_names = self.feature_names_

        importance = getattr(self.model, "feature_importances_", None)
        if importance is None:
            raise ValueError("model does not expose feature_importances_")

        return pd.Series(importance, index=list(feature_names)).sort_values(ascending=False)

    @staticmethod
    def _zscore(x: pd.Series) -> pd.Series:
        return (x - x.mean()) / (x.std(ddof=0) + EPS)

    @staticmethod
    def _require_panel_index(obj: pd.DataFrame | pd.Series, name: str) -> None:
        if not isinstance(obj.index, pd.MultiIndex):
            raise ValueError(f"{name} must be indexed by MultiIndex(date, ticker)")
        missing = {"date", "ticker"} - set(obj.index.names)
        if missing:
            raise ValueError(f"{name} index must include levels named date and ticker")

    def _build_model(self):
        lgb = self._import_lightgbm()

        return lgb.LGBMRegressor(
            n_estimators=self.config.n_estimators,
            max_depth=self.config.max_depth,
            learning_rate=self.config.learning_rate,
            random_state=self.config.random_state,
            n_jobs=self.config.n_jobs,
            verbose=-1,
        )

    @staticmethod
    def _import_lightgbm():
        try:
            import lightgbm as lgb

            return lgb
        except ImportError as exc:
            raise ImportError(
                "NonLinearAlphaPredictor requires LightGBM. Install it with `pip install lightgbm`."
            ) from exc
        except AttributeError:
            # LightGBM imports optional Dask adapters during module import.
            # Some research Anaconda stacks carry an old Dask build that is
            # incompatible with modern pandas, so we isolate the optional probe.
            saved = {name: sys.modules.get(name) for name in ("dask", "dask.dataframe")}
            sys.modules["dask"] = None
            sys.modules["dask.dataframe"] = None
            for name in list(sys.modules):
                if name == "lightgbm" or name.startswith("lightgbm."):
                    sys.modules.pop(name, None)
            try:
                import lightgbm as lgb

                return lgb
            finally:
                for name, module in saved.items():
                    if module is None:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = module
