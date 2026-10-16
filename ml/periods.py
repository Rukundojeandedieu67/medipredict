from __future__ import annotations

from typing import Literal

import pandas as pd

DataFrequency = Literal["daily", "monthly"]


def normalize_periods(
    frame: pd.DataFrame,
    frequency: DataFrequency,
    *,
    require_unique: bool = True,
) -> pd.DataFrame:
    if frequency not in ("daily", "monthly"):
        raise ValueError("frequency must be 'daily' or 'monthly'")
    required = {"facility_id", "item_id", "date"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Missing period key columns: {', '.join(missing)}")

    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], format="%Y-%m-%d", errors="raise")
    result["_period"] = result["date"].dt.to_period("D" if frequency == "daily" else "M")
    if require_unique and result.duplicated(["facility_id", "item_id", "_period"]).any():
        raise ValueError("Each facility-item must have at most one row per data-frequency period.")
    return result.sort_values(["facility_id", "item_id", "_period"], kind="stable").reset_index(drop=True)


def indexed_by_observation(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.duplicated(["facility_id", "item_id", "date"]).any():
        raise ValueError("Feature rows must be unique by facility_id, item_id, and date.")
    result = frame.set_index(["facility_id", "item_id", "date"], drop=False)
    result.index.names = ["facility_id", "item_id", "t"]
    return result


def parse_boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None
