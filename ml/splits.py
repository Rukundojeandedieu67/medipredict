from __future__ import annotations

from math import ceil
from typing import Literal

import pandas as pd

from .periods import DataFrequency


def _periods(frame: pd.DataFrame, frequency: DataFrequency) -> pd.Series:
    dates = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="raise")
    return dates.dt.to_period("D" if frequency == "daily" else "M")


def assign_time_splits(
    frame: pd.DataFrame,
    boundaries: dict[str, object],
    *,
    frequency: DataFrequency,
) -> pd.Series:
    """Assign rows by calendar boundaries without inspecting labels."""
    periods = _periods(frame, frequency)
    period_frequency = "D" if frequency == "daily" else "M"
    assignments = pd.Series(None, index=frame.index, dtype=object)
    for split_name in ("train", "validation", "test"):
        start = pd.Period(str(boundaries[f"{split_name}_period_start"]), freq=period_frequency)
        end = pd.Period(str(boundaries[f"{split_name}_period_end"]), freq=period_frequency)
        assignments.loc[(periods >= start) & (periods <= end)] = split_name
    return assignments


def _summary(frame: pd.DataFrame) -> dict[str, object]:
    labeled = frame.loc[frame["target"].notna()]
    positives = int(labeled["target"].astype(int).sum()) if len(labeled) else 0
    periods = pd.to_datetime(frame["date"])
    return {
        "row_count": len(frame),
        "labeled_row_count": len(labeled),
        "positive_count": positives,
        "label_prevalence": positives / len(labeled) if len(labeled) else None,
        "start": periods.min().date().isoformat() if len(periods) else None,
        "end": periods.max().date().isoformat() if len(periods) else None,
    }


def _check_positives(name: str, frame: pd.DataFrame, minimum: int) -> None:
    positives = int(frame["target"].dropna().astype(int).sum())
    if positives < minimum:
        raise ValueError(
            f"{name} split has {positives} positive labels; at least {minimum} are required."
        )


def time_based_split(
    frame: pd.DataFrame,
    *,
    horizon: int,
    frequency: DataFrequency,
    minimum_positives: int = 1,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
) -> dict[str, object]:
    """Make chronological splits with a purge of at least H complete periods."""
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if minimum_positives < 0:
        raise ValueError("minimum_positives cannot be negative")
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("split fractions must be between zero and one")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train_fraction + validation_fraction must be less than one")
    if "target" not in frame:
        raise ValueError("frame must contain target labels")

    periods = _periods(frame, frequency)
    observed_periods = sorted(periods.unique())
    calendar_periods = list(
        pd.period_range(
            start=observed_periods[0],
            end=observed_periods[-1],
            freq="D" if frequency == "daily" else "M",
        )
    )
    first_boundary = int(len(calendar_periods) * train_fraction)
    second_boundary = int(len(calendar_periods) * (train_fraction + validation_fraction))
    if first_boundary <= horizon or second_boundary - first_boundary <= horizon or len(calendar_periods) - second_boundary < 1:
        raise ValueError("Not enough time periods for requested splits and purge gaps.")

    train_end_index = first_boundary - horizon - 1
    validation_end_index = second_boundary - horizon - 1
    train_periods = set(calendar_periods[: train_end_index + 1])
    validation_periods = set(calendar_periods[first_boundary : validation_end_index + 1])
    test_periods = set(calendar_periods[second_boundary:])
    split_frames = {
        "train": frame.loc[periods.isin(train_periods) & frame["target"].notna()].copy(),
        "validation": frame.loc[periods.isin(validation_periods) & frame["target"].notna()].copy(),
        "test": frame.loc[periods.isin(test_periods) & frame["target"].notna()].copy(),
    }
    for name, split_frame in split_frames.items():
        _check_positives(name, split_frame, minimum_positives)

    boundaries = {
        "train": _summary(split_frames["train"]),
        "validation": _summary(split_frames["validation"]),
        "test": _summary(split_frames["test"]),
        "train_period_start": str(min(train_periods)),
        "train_period_end": str(max(train_periods)),
        "validation_period_start": str(min(validation_periods)),
        "validation_period_end": str(max(validation_periods)),
        "test_period_start": str(min(test_periods)),
        "test_period_end": str(max(test_periods)),
        "purge_gap_periods": horizon,
        "purged_before_validation": [
            period.start_time.date().isoformat()
            for period in calendar_periods[train_end_index + 1 : first_boundary]
        ],
        "purged_before_test": [
            period.start_time.date().isoformat()
            for period in calendar_periods[validation_end_index + 1 : second_boundary]
        ],
        "frequency": frequency,
        "horizon": horizon,
    }
    return {"splits": split_frames, "boundaries": boundaries}


def grouped_unseen_split(
    frame: pd.DataFrame,
    *,
    group_column: Literal["facility_id", "district"] = "facility_id",
    test_fraction: float = 0.2,
    minimum_positives: int = 1,
) -> dict[str, object]:
    """Hold out complete facilities or districts using deterministic sorted groups."""
    if group_column not in frame:
        raise ValueError(f"Grouped split column '{group_column}' is not present.")
    if "target" not in frame:
        raise ValueError("frame must contain target labels")
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between zero and one")
    if frame[group_column].isna().any():
        raise ValueError(f"Grouped split column '{group_column}' contains missing values.")
    groups = sorted(frame[group_column].dropna().astype(str).unique().tolist())
    if len(groups) < 2:
        raise ValueError(f"At least two distinct {group_column} values are required.")
    test_count = max(1, ceil(len(groups) * test_fraction))
    held_out = groups[-test_count:]
    test_mask = frame[group_column].astype(str).isin(held_out)
    split_frames = {
        "train": frame.loc[~test_mask & frame["target"].notna()].copy(),
        "test": frame.loc[test_mask & frame["target"].notna()].copy(),
    }
    for name, split_frame in split_frames.items():
        _check_positives(name, split_frame, minimum_positives)
    train_groups = set(split_frames["train"][group_column].astype(str))
    test_groups = set(split_frames["test"][group_column].astype(str))
    if train_groups.intersection(test_groups):
        raise RuntimeError("Grouped split assigned a group to both train and test.")
    return {
        "splits": split_frames,
        "boundaries": {
            "group_column": group_column,
            "train_groups": sorted(train_groups),
            "test_groups": sorted(test_groups),
            "train": _summary(split_frames["train"]),
            "test": _summary(split_frames["test"]),
        },
    }
