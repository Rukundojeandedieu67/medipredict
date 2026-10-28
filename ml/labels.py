from __future__ import annotations

from typing import Literal

import pandas as pd

from .periods import DataFrequency, indexed_by_observation, normalize_periods, parse_boolean

LabelMode = Literal["new_stockout", "any_stockout_in_window"]


def stockout_indicator(frame: pd.DataFrame, frequency: DataFrequency) -> pd.Series:
    stock = pd.to_numeric(frame["stock_on_hand"], errors="coerce")
    if frequency == "monthly" and "stock_out_days" in frame:
        days = pd.to_numeric(frame["stock_out_days"], errors="coerce")
        outcome = days.gt(0).where(days.notna(), stock.eq(0))
    else:
        outcome = stock.eq(0)
    if "stockout_flag" in frame:
        recorded = frame["stockout_flag"].map(parse_boolean)
        outcome = outcome | recorded.fillna(False)
    return outcome.fillna(False).astype(bool)


def build_labels(
    frame: pd.DataFrame,
    *,
    horizon: int,
    frequency: DataFrequency,
    label_mode: LabelMode = "new_stockout",
) -> pd.DataFrame:
    """Label observed stock-outs in (t, t+H], leaving incomplete windows unlabeled."""
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if label_mode not in ("new_stockout", "any_stockout_in_window"):
        raise ValueError("label_mode must be 'new_stockout' or 'any_stockout_in_window'")
    required = {"stock_on_hand"}
    if not required.issubset(frame.columns):
        raise ValueError("stock_on_hand is required to construct stock-out labels")

    data = normalize_periods(frame, frequency)
    data["_stockout"] = stockout_indicator(data, frequency).to_numpy()
    data["target"] = pd.Series(pd.NA, index=data.index, dtype="Int64")
    data["label_status"] = "unobserved_window"
    data["label_window_start"] = pd.NaT
    data["label_window_end"] = pd.NaT
    data["label_event_date"] = pd.NaT
    data["label_event_offset"] = pd.Series(pd.NA, index=data.index, dtype="Int64")

    for _, group in data.groupby(["facility_id", "item_id"], sort=False):
        positions = group.index.to_list()
        period_to_position = {data.at[position, "_period"]: position for position in positions}
        for position in positions:
            current_period = data.at[position, "_period"]
            data.at[position, "label_window_start"] = data.at[position, "date"]
            if label_mode == "new_stockout" and bool(data.at[position, "_stockout"]):
                data.at[position, "label_status"] = "excluded_current_stockout"
                continue

            future_periods = [
                current_period + offset for offset in range(1, horizon + 1)
            ]
            future_positions = [period_to_position.get(period) for period in future_periods]
            if any(future_position is None for future_position in future_positions):
                available_periods = set(period_to_position)
                if (
                    any(period in available_periods for period in future_periods)
                    or max(available_periods) > future_periods[-1]
                ):
                    data.at[position, "label_status"] = "unobserved_period"
                else:
                    data.at[position, "label_status"] = "unobserved_window"
                continue

            valid_positions = [int(value) for value in future_positions if value is not None]
            event_positions = [
                value for value in valid_positions if bool(data.at[value, "_stockout"])
            ]
            data.at[position, "target"] = int(bool(event_positions))
            data.at[position, "label_status"] = "observed"
            data.at[position, "label_window_end"] = data.at[valid_positions[-1], "date"]
            if event_positions:
                event_position = event_positions[0]
                data.at[position, "label_event_date"] = data.at[event_position, "date"]
                data.at[position, "label_event_offset"] = int(
                    (data.at[event_position, "_period"] - current_period).n
                )

    data = data.drop(columns=["_stockout", "_period"])
    data["label_window_start"] = pd.to_datetime(data["label_window_start"])
    data["label_window_end"] = pd.to_datetime(data["label_window_end"])
    data["label_event_date"] = pd.to_datetime(data["label_event_date"])
    return indexed_by_observation(data)


def label_prevalence(labels: pd.DataFrame) -> dict[str, object]:
    if "target" not in labels:
        raise ValueError("labels must contain a target column")
    observed = labels.loc[labels["target"].notna()].copy().reset_index(drop=True)

    def summary(frame: pd.DataFrame) -> dict[str, object]:
        count = len(frame)
        positives = int(frame["target"].astype(int).sum()) if count else 0
        return {
            "rows": count,
            "positives": positives,
            "prevalence": positives / count if count else None,
        }

    result: dict[str, object] = {"overall": summary(observed)}
    for column in ("facility_type", "district", "item_id"):
        if column not in observed.columns:
            result[column] = []
            continue
        grouped = []
        observed[column] = observed[column].fillna("Unknown").astype(str)
        for value, group in observed.groupby(column, dropna=False, sort=True):
            grouped.append({"value": str(value), **summary(group)})
        result[column] = grouped
    result["excluded_rows"] = int(labels["target"].isna().sum())
    result["label_status_counts"] = {
        str(status): int(count)
        for status, count in labels["label_status"].value_counts(dropna=False).items()
    }
    return result
