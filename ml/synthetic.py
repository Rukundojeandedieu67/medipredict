from __future__ import annotations

import argparse
from calendar import monthrange
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd


def generate_synthetic_supply_history(
    *,
    facilities: int = 24,
    periods: int = 72,
    seed: int = 20261016,
    replenishment_cycle_days: int = 42,
    frequency: Literal["monthly", "daily"] = "monthly",
) -> pd.DataFrame:
    """Simulate supply dynamics; this data is only for pipeline signal-recovery tests."""
    if facilities < 2 or periods < 24 or replenishment_cycle_days < 14:
        raise ValueError(
            "Need at least 2 facilities, 24 periods, and a 14-day replenishment cycle."
        )
    if frequency not in ("monthly", "daily"):
        raise ValueError("frequency must be 'monthly' or 'daily'")

    rng = np.random.default_rng(seed)
    if frequency == "monthly":
        month_starts = pd.date_range("2020-01-01", periods=periods, freq="MS")
        dates = [
            pd.Timestamp(day)
            for month_start in month_starts
            for day in pd.date_range(
                month_start,
                periods=monthrange(month_start.year, month_start.month)[1],
                freq="D",
            )
        ]
    else:
        dates = list(pd.date_range("2020-01-01", periods=periods, freq="D"))

    daily_rows: list[dict[str, object]] = []
    for facility_index in range(facilities):
        facility_id = f"SYN-FAC-{facility_index:03d}"
        base_demand = float(rng.uniform(7, 15))
        phase = float(rng.uniform(0, 2 * np.pi))
        seasonal_amplitude = float(rng.uniform(0.3, 0.65))
        lead_time = int(rng.integers(10, 31))
        cycle = replenishment_cycle_days + int(rng.integers(-4, 5))
        reorder_level = base_demand * lead_time * 1.25
        stock = base_demand * cycle * float(rng.uniform(0.35, 0.65))
        next_order = max(0, cycle - lead_time)
        receipts_by_day: dict[int, float] = {}
        demand_history: list[float] = []

        for day_index, observed_date in enumerate(dates):
            year_phase = 2 * np.pi * day_index / 365.25 + phase
            seasonal_factor = 1 + seasonal_amplitude * np.sin(year_phase)
            demand = max(
                0.25,
                base_demand * seasonal_factor
                + float(rng.normal(0, base_demand * 0.12)),
            )
            demand_history.append(demand)
            receipt = receipts_by_day.pop(day_index, 0.0)

            if day_index == next_order:
                recent_mean = float(np.mean(demand_history[-28:]))
                delay = lead_time + int(rng.integers(0, 15))
                order_size = recent_mean * cycle * float(rng.uniform(0.82, 1.12))
                delivery_day = day_index + delay
                receipts_by_day[delivery_day] = (
                    receipts_by_day.get(delivery_day, 0.0) + order_size
                )
                next_order += cycle

            stock += receipt
            consumed = min(stock, demand)
            stock = max(0.0, stock - consumed)
            daily_rows.append(
                {
                    "facility_id": facility_id,
                    "item_id": "SYN-ITEM-ANTIMALARIAL",
                    "date": observed_date,
                    "stock_on_hand": round(stock, 3),
                    "units_consumed": round(consumed, 3),
                    "units_received": round(receipt, 3),
                    "is_synthetic": True,
                    "stockout_flag": stock <= 1e-9,
                    "lead_time_days": lead_time,
                    "reorder_level": round(reorder_level, 3),
                    "facility_type": ("Health Centre", "Health Post", "District Hospital")[
                        facility_index % 3
                    ],
                    "district": f"SYN-DIST-{facility_index % 8:02d}",
                    "item_category": "antimalarial",
                    "program_funded": facility_index % 2 == 0,
                    "cold_chain": False,
                }
            )

    daily = pd.DataFrame(daily_rows)
    if frequency == "daily":
        daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
        return daily

    daily["_month"] = daily["date"].dt.to_period("M")
    monthly = (
        daily.groupby(["facility_id", "item_id", "_month"], sort=True)
        .agg(
            date=("date", "max"),
            stock_on_hand=("stock_on_hand", "last"),
            units_consumed=("units_consumed", "sum"),
            units_received=("units_received", "sum"),
            stock_out_days=("stockout_flag", "sum"),
            stockout_flag=("stockout_flag", "any"),
            lead_time_days=("lead_time_days", "first"),
            reorder_level=("reorder_level", "first"),
            facility_type=("facility_type", "first"),
            district=("district", "first"),
            item_category=("item_category", "first"),
            program_funded=("program_funded", "first"),
            cold_chain=("cold_chain", "first"),
            is_synthetic=("is_synthetic", "all"),
        )
        .reset_index()
    )
    monthly = monthly.drop(columns="_month")
    monthly["date"] = monthly["date"].dt.strftime("%Y-%m-%d")
    return monthly


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic supply histories for pipeline signal-recovery tests."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--facilities", type=int, default=24)
    parser.add_argument("--periods", type=int, default=72)
    parser.add_argument("--frequency", choices=("monthly", "daily"), default="monthly")
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--cycle-days", type=int, default=42)
    args = parser.parse_args()
    frame = generate_synthetic_supply_history(
        facilities=args.facilities,
        periods=args.periods,
        seed=args.seed,
        replenishment_cycle_days=args.cycle_days,
        frequency=args.frequency,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False)
    print(
        "SYNTHETIC - not evidence of real-world performance "
        f"| frequency={args.frequency} | rows={len(frame)} | output={args.output}"
    )


if __name__ == "__main__":
    main()
