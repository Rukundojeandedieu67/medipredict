from __future__ import annotations

from typing import Any

import pandas as pd

from .periods import DataFrequency


_MISSING_TEXT = {"", "na", "n/a", "nan", "none", "null", "<na>"}


def _missing_values(values: pd.Series) -> pd.Series:
    return values.isna() | values.map(
        lambda value: isinstance(value, str) and value.strip().casefold() in _MISSING_TEXT
    )


def profile_inventory_missingness(
    frame: pd.DataFrame,
    *,
    frequency: DataFrequency,
) -> dict[str, Any]:
    """Measure reported-value missingness separately from absent facility-item periods."""
    required = {"facility_id", "item_id", "date"}
    absent = sorted(required.difference(frame.columns))
    if absent:
        raise ValueError(f"Missingness profile requires columns: {', '.join(absent)}")
    if frequency not in ("daily", "monthly"):
        raise ValueError("frequency must be 'daily' or 'monthly'")

    data = frame.copy()
    dates = pd.to_datetime(data["date"], format="%Y-%m-%d", errors="raise")
    period_frequency = "D" if frequency == "daily" else "M"
    data["_period"] = dates.dt.to_period(period_frequency)
    if data.duplicated(["facility_id", "item_id", "_period"]).any():
        raise ValueError("Missingness profile requires unique facility-item-period rows.")

    measured_columns = [
        column for column in data.columns
        if column not in {"facility_id", "item_id", "date", "_period", "is_synthetic"}
    ]
    explicit_missing = {
        column: int(_missing_values(data[column]).sum())
        for column in measured_columns
    }
    per_facility: dict[str, dict[str, int]] = {}
    pair_count = 0
    total_expected_periods = 0
    total_missing_periods = 0
    for (facility_id, _item_id), group in data.groupby(
        ["facility_id", "item_id"], dropna=False, sort=True
    ):
        periods = group["_period"].sort_values().drop_duplicates()
        expected = len(pd.period_range(periods.iloc[0], periods.iloc[-1], freq=period_frequency))
        missing_periods = expected - len(periods)
        key = str(facility_id)
        summary = per_facility.setdefault(
            key,
            {"facility_item_pairs": 0, "observed_rows": 0, "expected_periods": 0, "missing_periods": 0},
        )
        summary["facility_item_pairs"] += 1
        summary["observed_rows"] += len(group)
        summary["expected_periods"] += expected
        summary["missing_periods"] += missing_periods
        pair_count += 1
        total_expected_periods += expected
        total_missing_periods += missing_periods

    facility_rows = [
        {"facility_id": facility_id, **summary}
        for facility_id, summary in sorted(per_facility.items())
    ]
    return {
        "frequency": frequency,
        "source_rows": len(data),
        "facility_count": len(per_facility),
        "facility_item_pair_count": pair_count,
        "expected_periods_within_observed_ranges": total_expected_periods,
        "missing_report_periods_within_observed_ranges": total_missing_periods,
        "explicit_missing_values_by_column": explicit_missing,
        "facility_summaries": facility_rows,
        "interpretation": (
            "Missing periods count absent reports only between each facility-item's first and last observed periods. "
            "Explicit missing cells are counted separately. Zero values are observed values, not missing reports. "
            "No values or rows are imputed by this profile."
        ),
    }
