"""Algorithmic execution sandbox for Lingyu Quant."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ExecutionPerformance:
    """Execution cost comparison between naive and VWAP schedules."""

    naive_avg_price: float
    algo_avg_price: float
    arrival_price: float
    saved_bps: float
    naive_cost_bps: float
    algo_cost_bps: float


class VWAPExecutionEngine:
    """
    A-share VWAP execution planner with a U-shaped intraday volume profile.

    The engine splits a target order across 24 ten-minute windows, caps each
    slice by the configured participation rate, and provides a simple execution
    cost sandbox against a naive open-window order.
    """

    windows_per_day = 24

    def __init__(
        self,
        target_volume: int,
        adv: int,
        max_participation_rate: float = 0.15,
        side: str = "buy",
        random_seed: int = 42,
    ) -> None:
        if target_volume <= 0:
            raise ValueError("target_volume must be positive.")
        if adv <= 0:
            raise ValueError("adv must be positive.")
        if not 0 < max_participation_rate <= 1:
            raise ValueError("max_participation_rate must be in (0, 1].")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'.")

        self.target_volume = int(target_volume)
        self.adv = int(adv)
        self.max_participation_rate = float(max_participation_rate)
        self.side = side
        self.random_seed = random_seed

    def _generate_historical_u_profile(self) -> np.ndarray:
        """
        Generate a normalized U-shaped A-share intraday volume profile.

        A-share cash trading is four hours long. We split it into 24 ten-minute
        windows, then use a parabola centered at midday: open and close windows
        are heavier, the middle session is quieter.
        """

        x = np.linspace(-1.0, 1.0, self.windows_per_day)
        raw = 0.55 + 1.9 * (x**2)
        raw[:3] *= np.array([1.45, 1.25, 1.1])
        raw[-3:] *= np.array([1.1, 1.25, 1.45])
        return raw / raw.sum()

    def calculate_execution_schedule(self) -> pd.DataFrame:
        """Return a 24-window VWAP execution schedule."""

        weights = self._generate_historical_u_profile()
        predicted_market_volume = self.adv * weights
        desired_volume = self.target_volume * weights
        max_slice_volume = predicted_market_volume * self.max_participation_rate
        planned = np.minimum(desired_volume, max_slice_volume)
        planned = self._round_lot_constrained(planned, max_slice_volume)

        schedule = pd.DataFrame(
            {
                "time_slice": self._time_slices(),
                "u_profile_weight": weights,
                "predicted_market_volume": predicted_market_volume,
                "planned_order_volume": planned,
            }
        )
        schedule["participation_rate"] = schedule["planned_order_volume"] / schedule[
            "predicted_market_volume"
        ].replace(0, np.nan)
        schedule["participation_rate"] = schedule["participation_rate"].fillna(0.0)
        schedule["cumulative_order_volume"] = schedule["planned_order_volume"].cumsum()
        schedule.attrs["target_volume"] = self.target_volume
        schedule.attrs["planned_total_volume"] = float(schedule["planned_order_volume"].sum())
        schedule.attrs["unfilled_volume"] = float(max(0.0, self.target_volume - schedule.attrs["planned_total_volume"]))
        return schedule

    def simulate_execution_performance(
        self,
        base_price: float = 10.0,
        daily_volatility: float = 0.025,
        impact_coefficient: float = 0.08,
    ) -> tuple[pd.DataFrame, ExecutionPerformance]:
        """
        Compare naive open-window execution with VWAP sliced execution.

        ``saved_bps`` is positive when the VWAP algorithm achieves a better
        average price than the naive order for the configured side.
        """

        if base_price <= 0:
            raise ValueError("base_price must be positive.")
        if daily_volatility < 0:
            raise ValueError("daily_volatility cannot be negative.")

        schedule = self.calculate_execution_schedule()
        rng = np.random.default_rng(self.random_seed)
        shocks = rng.normal(0.0, daily_volatility / np.sqrt(self.windows_per_day), self.windows_per_day)
        prices = base_price * np.exp(np.cumsum(shocks))

        naive_volume = self._allocate_naive_open_volume(schedule["predicted_market_volume"].to_numpy())
        algo_volume = schedule["planned_order_volume"].to_numpy(dtype=float)
        market_volume = schedule["predicted_market_volume"].to_numpy(dtype=float)

        direction = 1.0 if self.side == "buy" else -1.0
        naive_fill_prices = prices * (
            1.0
            + direction
            * impact_coefficient
            * np.square(naive_volume / np.maximum(market_volume, 1.0))
        )
        algo_fill_prices = prices * (
            1.0
            + direction
            * impact_coefficient
            * np.square(algo_volume / np.maximum(market_volume, 1.0))
        )

        naive_avg = self._weighted_avg_price(naive_fill_prices, naive_volume)
        algo_avg = self._weighted_avg_price(algo_fill_prices, algo_volume)
        arrival = float(prices[0])

        if self.side == "buy":
            saved_bps = (naive_avg - algo_avg) / arrival * 10_000
            naive_cost_bps = (naive_avg - arrival) / arrival * 10_000
            algo_cost_bps = (algo_avg - arrival) / arrival * 10_000
        else:
            saved_bps = (algo_avg - naive_avg) / arrival * 10_000
            naive_cost_bps = (arrival - naive_avg) / arrival * 10_000
            algo_cost_bps = (arrival - algo_avg) / arrival * 10_000

        comparison = schedule.copy()
        comparison["simulated_mid_price"] = prices
        comparison["naive_order_volume"] = naive_volume
        comparison["naive_fill_price"] = naive_fill_prices
        comparison["algo_fill_price"] = algo_fill_prices

        return comparison, ExecutionPerformance(
            naive_avg_price=float(naive_avg),
            algo_avg_price=float(algo_avg),
            arrival_price=arrival,
            saved_bps=float(saved_bps),
            naive_cost_bps=float(naive_cost_bps),
            algo_cost_bps=float(algo_cost_bps),
        )

    def _round_lot_constrained(self, desired: np.ndarray, cap: np.ndarray) -> np.ndarray:
        planned = np.floor(desired / 100.0) * 100.0
        planned = np.minimum(planned, np.floor(cap / 100.0) * 100.0)

        remaining = self.target_volume - planned.sum()
        if remaining <= 0:
            return planned

        spare_capacity = np.floor((cap - planned) / 100.0) * 100.0
        order = np.argsort(-spare_capacity)
        for idx in order:
            add = min(spare_capacity[idx], np.floor(remaining / 100.0) * 100.0)
            if add <= 0:
                break
            planned[idx] += add
            remaining -= add
        return planned

    def _allocate_naive_open_volume(self, market_volume: np.ndarray) -> np.ndarray:
        naive = np.zeros(self.windows_per_day, dtype=float)
        remaining = float(self.target_volume)
        for idx in range(3):
            take = min(remaining, market_volume[idx] * min(1.0, self.max_participation_rate * 3.0))
            naive[idx] = take
            remaining -= take
        if remaining > 0:
            naive[2] += remaining
        return naive

    @staticmethod
    def _weighted_avg_price(prices: np.ndarray, volumes: np.ndarray) -> float:
        total = volumes.sum()
        if total <= 0:
            return float("nan")
        return float(np.sum(prices * volumes) / total)

    @staticmethod
    def _time_slices() -> list[str]:
        morning = pd.date_range("09:30", periods=12, freq="10min").strftime("%H:%M").tolist()
        afternoon = pd.date_range("13:00", periods=12, freq="10min").strftime("%H:%M").tolist()
        return morning + afternoon
