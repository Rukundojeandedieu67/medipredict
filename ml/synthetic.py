from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def generate_synthetic_supply_history(
    *,
    facilities: int = 24,
    periods: int = 900,
    seed: int = 20261016,
    replenishment_cycle_days: int = 42,
) -> pd.DataFrame:
    """Simulate stock dynamics with seasonal demand and stochastic supply delays."""
    if facilities < 2 or periods < 120 or replenishment_cycle_days < 14:
        raise ValueError("Need at least 2 facilities, 120 periods, and a 14-day replenishment cycle.")
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=periods, freq="D")
    rows: list[dict[str, object]] = []
    for facility_index in range(facilities):
        facility_id = f"SYN-FAC-{facility_index:03d}"
        base_demand = float(rng.uniform(7, 15))
        phase = float(rng.uniform(0, 2 * np.pi))
        seasonal_amplitude = float(rng.uniform(0.3, 0.65))
        lead_time = int(rng.integers(3, 9))
        cycle = replenishment_cycle_days + int(rng.integers(-4, 5))
        target_stock = base_demand * cycle * float(rng.uniform(0.68, 0.82))
        stock = target_stock * float(rng.uniform(0.9, 1.1))
        next_order = lead_time + int(rng.integers(0, cycle))
        receipts_by_day: dict[int, float] = {}
        demand_history: list[float] = []
        for day_index, observed_date in enumerate(dates):
            seasonal_factor = 1 + seasonal_amplitude * np.sin(
                2 * np.pi * day_index / 365.25 + phase
            )
            demand = max(
                0.25,
                base_demand * seasonal_factor + float(rng.normal(0, base_demand * 0.12)),
            )
            demand_history.append(demand)

            receipt = receipts_by_day.pop(day_index, 0.0)
            if day_index == next_order:
                recent_mean = float(np.mean(demand_history[-28:]))
                delay = lead_time + int(rng.integers(2, 11))
                order_size = recent_mean * cycle * float(rng.uniform(0.82, 1.08))
                receipts_by_day[day_index + delay] = (
                    receipts_by_day.get(day_index + delay, 0.0) + order_size
                )
                next_order += cycle

            stock += receipt
            consumed = min(stock, demand)
            stock = max(0.0, stock - consumed)
            rows.append(
                {
                    "facility_id": facility_id,
                    "item_id": "SYN-ITEM-ANTIMALARIAL",
                    "date": observed_date.date().isoformat(),
                    "stock_on_hand": round(stock, 3),
                    "units_consumed": round(consumed, 3),
                    "units_received": round(receipt, 3),
                    "is_synthetic": True,
                    "stockout_flag": stock <= 1e-9,
                    "lead_time_days": lead_time,
                    "reorder_level": round(base_demand * lead_time * 1.25, 3),
                    "facility_type": ("Health Centre", "Health Post", "District Hospital")[
                        facility_index % 3
                    ],
                    "district": f"SYN-DIST-{facility_index % 8:02d}",
                    "item_category": "antimalarial",
                    "program_funded": facility_index % 2 == 0,
                    "cold_chain": False,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic stock histories for pipeline signal-recovery tests."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--facilities", type=int, default=24)
    parser.add_argument("--periods", type=int, default=900)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--cycle-days", type=int, default=42)
    args = parser.parse_args()
    frame = generate_synthetic_supply_history(
        facilities=args.facilities,
        periods=args.periods,
        seed=args.seed,
        replenishment_cycle_days=args.cycle_days,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False)
    print(
        "SYNTHETIC - not evidence of real-world performance "
        f"| rows={len(frame)} | output={args.output}"
    )


if __name__ == "__main__":
    main()
