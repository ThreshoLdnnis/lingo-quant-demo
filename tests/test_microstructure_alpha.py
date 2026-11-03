import ast
from pathlib import Path

import numpy as np
import pandas as pd

from lingyu_quant.microstructure_alpha import MicrostructureAlphaEngine


def make_session(ticker, scenario, start="2026-06-01 09:31:00", minutes=8):
    dt = pd.date_range(start, periods=minutes, freq="30min")
    if scenario == "smart":
        close = np.array([10.00, 9.98, 9.97, 9.99, 10.01, 10.02, 10.03, 10.04])
        volume = np.array([1000, 1020, 1010, 1030, 1005, 1040, 1025, 1035])
    elif scenario == "pulse":
        close = np.array([10.00, 10.35, 10.30, 10.18, 10.10, 10.04, 10.02, 10.00])
        volume = np.array([9000, 850, 760, 720, 700, 680, 690, 710])
    else:
        close = np.array([10.00, 9.96, 9.92, 9.91, 9.90, 9.92, 9.93, 9.95])
        volume = np.array([1200, 5000, 5200, 4900, 4800, 1500, 1400, 1600])

    return pd.DataFrame(
        {
            "date": dt,
            "ticker": ticker,
            "open": close,
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
            "volume": volume,
            "amount": close * volume,
        }
    )


def test_microstructure_factors_and_score_are_daily_cross_sectional():
    minute_data = pd.concat(
        [
            make_session("000001.SZ", "smart"),
            make_session("000002.SZ", "pulse"),
            make_session("600000.SH", "support"),
        ],
        ignore_index=True,
    )

    factors = MicrostructureAlphaEngine(minute_data).extract_smart_money_factors()

    assert factors.index.names == ["date", "ticker"]
    assert len(factors) == 3
    assert {
        "vwap_accumulation",
        "pulse_penalty",
        "downside_support",
        "volume_entropy",
        "pre_close_strength",
        "smart_money_raw",
        "smart_money_score",
    }.issubset(factors.columns)
    assert abs(factors["smart_money_score"].mean()) < 1e-8
    assert factors.xs("000002.SZ", level="ticker")["pulse_penalty"].iloc[0] > 4
    assert factors.xs("000001.SZ", level="ticker")["volume_entropy"].iloc[0] > factors.xs(
        "000002.SZ", level="ticker"
    )["volume_entropy"].iloc[0]


def test_microstructure_engine_accepts_datetime_alias():
    frame = make_session("000001.SZ", "smart").rename(columns={"date": "datetime"})
    factors = MicrostructureAlphaEngine(frame).extract_smart_money_factors()
    assert ("2026-06-01" in str(factors.index.get_level_values("date")[0]))


def test_microstructure_module_has_no_explicit_for_or_while_loops():
    tree = ast.parse(Path("lingyu_quant/microstructure_alpha.py").read_text())
    loops = [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While))]
    assert loops == []
