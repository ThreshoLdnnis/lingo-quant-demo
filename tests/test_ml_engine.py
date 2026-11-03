import importlib.util

import numpy as np
import pandas as pd
import pytest

from lingyu_quant.ml_engine import NonLinearAlphaPredictor


def make_panel(days=6, tickers=("000001.SZ", "000002.SZ", "600000.SH")):
    dates = pd.date_range("2026-06-01", periods=days, freq="B")
    index = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])

    features = pd.DataFrame(
        {
            "smart_money_score": np.linspace(-1.0, 1.0, len(index)),
            "volume_entropy": np.tile([4.8, 5.2, 5.5], days),
            "pulse_penalty": np.tile([1.2, 4.5, 2.1], days),
        },
        index=index,
    )
    base = np.tile([10.0, 20.0, 30.0], days)
    ticker_slopes = np.tile([0.1, 0.3, 0.2], days)
    day_steps = np.repeat(np.arange(days), len(tickers))
    close = pd.Series(base + day_steps * ticker_slopes, index=index, name="close")
    return features, close


def test_align_features_and_labels_uses_t_plus_2_cross_sectional_rank():
    features, close = make_panel()
    predictor = object.__new__(NonLinearAlphaPredictor)

    X, y = predictor.align_features_and_labels(features, close)

    assert X.index.equals(y.index)
    assert X.index.get_level_values("date").max() == features.index.get_level_values("date").unique()[-3]
    assert np.allclose(y.groupby(level="date").min(), -1 / 3)
    assert np.allclose(y.groupby(level="date").max(), 1.0)


@pytest.mark.skipif(importlib.util.find_spec("lightgbm") is None, reason="LightGBM is not installed")
def test_train_and_predict_returns_daily_zscored_alpha():
    features, close = make_panel(days=8)
    predictor = NonLinearAlphaPredictor(n_estimators=8, max_depth=3, learning_rate=0.1)
    X, y = predictor.align_features_and_labels(features, close)

    train_dates = X.index.get_level_values("date") < X.index.get_level_values("date").max()
    preds = predictor.train_and_predict(X.loc[train_dates], y.loc[train_dates], X.loc[~train_dates])

    assert preds.name == "ml_alpha_norm"
    assert preds.index.equals(X.loc[~train_dates].index)
    assert abs(preds.groupby(level="date").mean().iloc[0]) < 1e-8
    assert list(predictor.get_feature_importance().index) == list(X.columns)
