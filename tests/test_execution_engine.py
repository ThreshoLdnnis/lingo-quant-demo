import numpy as np
import pandas as pd
import pytest

from lingyu_quant.execution_engine import ExecutionPerformance, VWAPExecutionEngine


def test_u_profile_has_24_windows_and_u_shape():
    engine = VWAPExecutionEngine(target_volume=120_000, adv=2_000_000)

    profile = engine._generate_historical_u_profile()

    assert len(profile) == 24
    assert np.isclose(profile.sum(), 1.0)
    assert profile[0] > profile[11]
    assert profile[-1] > profile[12]
    assert profile[0] > profile[5]
    assert profile[-1] > profile[18]


def test_execution_schedule_respects_participation_cap():
    engine = VWAPExecutionEngine(target_volume=120_000, adv=2_000_000, max_participation_rate=0.15)

    schedule = engine.calculate_execution_schedule()

    assert isinstance(schedule, pd.DataFrame)
    assert len(schedule) == 24
    assert {
        "time_slice",
        "predicted_market_volume",
        "planned_order_volume",
        "participation_rate",
    }.issubset(schedule.columns)
    assert schedule["planned_order_volume"].sum() == 120_000
    assert schedule["participation_rate"].max() <= 0.15 + 1e-12
    assert schedule.attrs["unfilled_volume"] == 0
    assert schedule["time_slice"].iloc[0] == "09:30"
    assert schedule["time_slice"].iloc[12] == "13:00"


def test_schedule_reports_unfilled_volume_when_order_exceeds_capacity():
    engine = VWAPExecutionEngine(target_volume=400_000, adv=1_000_000, max_participation_rate=0.15)

    schedule = engine.calculate_execution_schedule()

    assert schedule["planned_order_volume"].sum() <= 150_000
    assert schedule.attrs["unfilled_volume"] > 0
    assert schedule["participation_rate"].max() <= 0.15 + 1e-12


def test_simulate_execution_performance_reports_bps_savings():
    engine = VWAPExecutionEngine(
        target_volume=120_000,
        adv=2_000_000,
        max_participation_rate=0.15,
        random_seed=7,
    )

    comparison, perf = engine.simulate_execution_performance(base_price=10.0, daily_volatility=0.0)

    assert len(comparison) == 24
    assert isinstance(perf, ExecutionPerformance)
    assert perf.naive_avg_price > perf.algo_avg_price
    assert perf.saved_bps > 0
    assert perf.naive_cost_bps > perf.algo_cost_bps
    assert {"naive_order_volume", "naive_fill_price", "algo_fill_price"}.issubset(comparison.columns)


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        VWAPExecutionEngine(target_volume=0, adv=1_000_000)
    with pytest.raises(ValueError):
        VWAPExecutionEngine(target_volume=10_000, adv=0)
    with pytest.raises(ValueError):
        VWAPExecutionEngine(target_volume=10_000, adv=1_000_000, max_participation_rate=1.5)
    with pytest.raises(ValueError):
        VWAPExecutionEngine(target_volume=10_000, adv=1_000_000, side="hold")
