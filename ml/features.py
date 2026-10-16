from __future__ import annotations

from datetime import date, timedelta
from calendar import monthrange
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .periods import DataFrequency, indexed_by_observation, normalize_periods, parse_boolean

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CALENDAR_PATH = ROOT / "ml" / "config" / "rwanda_calendar.json"
OPTIONAL_ATTRIBUTES = (
    "facility_type",
    "district",
    "urban_rural",
    "catchment_population",
    "item_category",
    "program_funded",
    "cold_chain",
    "lead_time_days",
    "rainfall_anomaly",
    "temperature_anomaly",
    "outbreak_flag",
)
def _load_calendar(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "calendar_coverage_years",
        "seasons",
        "umuganda_weeks",
        "national_commemoration_periods",
        "public_holidays",
    ):
        if key not in data:
            raise ValueError(f"Calendar configuration is missing '{key}'")
    years = {int(year) for year in data["calendar_coverage_years"]}
    for table in ("umuganda_weeks", "national_commemoration_periods"):
        for value in data[table]:
            start = date.fromisoformat(value["start"])
            end = date.fromisoformat(value["end"])
            if end < start:
                raise ValueError(f"Calendar entry in '{table}' ends before it starts")
    for value in data["public_holidays"]:
        date.fromisoformat(value)
    return {**data, "_coverage_years": years}


def _period_delta(period: pd.Period, offset: int) -> pd.Period:
    return period - offset


def _number(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if np.isfinite(number) else float("nan")


def _safe_ratio(numerator: float, denominator: float, cap: float | None = None) -> float:
    if not np.isfinite(numerator) or not np.isfinite(denominator) or denominator <= 0:
        return float("nan")
    value = numerator / denominator
    return min(value, cap) if cap is not None else value


def _date_in_ranges(value: date, ranges: list[dict[str, str]]) -> bool:
    return any(date.fromisoformat(item["start"]) <= value <= date.fromisoformat(item["end"]) for item in ranges)


def _season(month: int, calendar: dict[str, Any]) -> str:
    for item in calendar["seasons"]:
        if month in item["months"]:
            return str(item["name"])
    raise ValueError(f"Month {month} is not assigned to a season")


def _window_periods(period: pd.Period, window: int) -> list[pd.Period]:
    return [_period_delta(period, offset) for offset in range(window - 1, -1, -1)]


class FeatureBuilder:
    """Build point-in-time features; fit only records in the training partition."""

    def __init__(
        self,
        *,
        frequency: DataFrequency,
        horizon: int | None = None,
        calendar_path: str | Path | None = None,
        cover_cap: float | None = None,
    ):
        if frequency not in ("daily", "monthly"):
            raise ValueError("frequency must be 'daily' or 'monthly'")
        if horizon is not None and horizon < 1:
            raise ValueError("horizon must be positive")
        self.frequency = frequency
        self.horizon = horizon or (14 if frequency == "daily" else 1)
        self.cover_cap = cover_cap or (365.0 if frequency == "daily" else 120.0)
        if self.cover_cap <= 0:
            raise ValueError("cover_cap must be positive")
        self.calendar_path = Path(calendar_path) if calendar_path else DEFAULT_CALENDAR_PATH
        self._calendar = _load_calendar(self.calendar_path)
        self.umuganda_rule_enabled = bool(
            self._calendar.get("umuganda_last_saturday_enabled", True)
        )
        self._fitted = False
        self._training_period_end: pd.Period | None = None
        self._optional_columns: tuple[str, ...] = ()
        self._district_replenishment_supplied = False
        self.feature_list: list[str] = []
        self.feature_availability: dict[str, str | None] = {}
        self.feature_lineage: dict[str, dict[str, object]] = {}
        self.windows = (7, 14, 28) if frequency == "daily" else (3, 6, 12)
        self.unit = "days" if frequency == "daily" else "months"
        self.cover_name = "days_of_cover" if frequency == "daily" else "months_of_stock"

    def fit(self, train: pd.DataFrame) -> FeatureBuilder:
        if train.empty:
            raise ValueError("FeatureBuilder.fit requires non-empty training rows")
        normalized = normalize_periods(train, self.frequency)
        self._training_period_end = normalized["_period"].max()
        self._optional_columns = tuple(
            column
            for column in OPTIONAL_ATTRIBUTES
            if column in normalized.columns and self._has_observed_values(normalized[column])
        )
        self._district_replenishment_supplied = (
            "district_replenishment_date" in normalized.columns
            and self._has_observed_values(normalized["district_replenishment_date"])
        )
        self.feature_list = self._feature_names()
        self.feature_availability = self._availability_reasons()
        self.feature_lineage = {}
        for name in self.feature_list:
            if name.startswith("consumption_"):
                source = "units_consumed"
            elif name.startswith(("receipt_", "mean_receipt", "receipts_to_consumption", "periods_since_last_receipt")):
                source = "units_received"
            elif name.startswith(("stock_to_", "days_of_cover", "months_of_stock")):
                source = "stock_on_hand"
            elif name.startswith(("historical_stockout", "periods_since_last_stockout")):
                source = "stock_on_hand, stockout_flag, stock_out_days"
            else:
                source = name
            self.feature_lineage[name] = {"source": source, "max_time_offset": 0}
        self._fitted = True
        return self

    def state_dict(self) -> dict[str, Any]:
        if not self._fitted or self._training_period_end is None:
            raise RuntimeError("FeatureBuilder.fit(train) must be called before state_dict().")
        return {
            "frequency": self.frequency,
            "horizon": self.horizon,
            "cover_cap": self.cover_cap,
            "calendar_configuration": json.loads(
                self.calendar_path.read_text(encoding="utf-8")
            ),
            "training_period_end": self._training_period_end.start_time.isoformat(),
            "optional_columns": list(self._optional_columns),
            "district_replenishment_supplied": self._district_replenishment_supplied,
            "umuganda_rule_enabled": self.umuganda_rule_enabled,
            "feature_list": self.feature_list.copy(),
            "feature_availability": self.feature_availability.copy(),
            "feature_lineage": self.feature_lineage.copy(),
        }

    @staticmethod
    def _has_observed_values(values: pd.Series) -> bool:
        return bool(
            values.map(
                lambda value: value is not None
                and str(value).strip().casefold() not in {"", "nan", "none", "<na>"}
            ).any()
        )

    def _feature_names(self) -> list[str]:
        names: list[str] = []
        for window in self.windows:
            suffix = f"{window}_{self.unit}"
            names.extend(
                (
                    f"consumption_mean_{suffix}",
                    f"consumption_std_{suffix}",
                    f"consumption_min_{suffix}",
                    f"consumption_max_{suffix}",
                )
            )
        names.extend(
            (
                f"consumption_cv_{self.windows[-1]}_{self.unit}",
                f"consumption_trend_slope_{self.windows[-1]}_{self.unit}",
                self.cover_name,
                "stock_to_reorder_level_ratio",
                "stock_to_historical_median_ratio",
                f"consumption_zero_streak_{self.unit}",
                f"periods_since_last_receipt_{self.unit}",
                f"receipt_frequency_{self.windows[-1]}_{self.unit}",
                f"mean_receipt_size_{self.windows[-1]}_{self.unit}",
                f"receipts_to_consumption_ratio_{self.windows[-1]}_{self.unit}",
                "historical_stockout_count",
                f"periods_since_last_stockout_{self.unit}",
                f"historical_stockout_duration_mean_{self.unit}",
                f"reporting_completeness_{self.windows[-1]}_{self.unit}",
                "month",
                "rwanda_season",
                "umuganda_week",
                "national_commemoration_period",
                f"public_holiday_count_next_{self.horizon}_{self.unit}",
                "quarter_end_period",
                f"periods_since_district_replenishment_{self.unit}",
            )
        )
        if self.frequency == "daily":
            names.append("week_of_year")
        names.extend(OPTIONAL_ATTRIBUTES)
        return names

    def _availability_reasons(self) -> dict[str, str | None]:
        reasons: dict[str, str | None] = {}
        calendar_years = self._calendar["_coverage_years"]
        for feature in self.feature_list:
            reason = None
            if feature == "umuganda_week" and self.umuganda_rule_enabled:
                reason = "Computed rule: last Saturday of month; confirm operational interpretation with RMS / RBC / MoH."
            elif feature == "umuganda_week" and not calendar_years:
                reason = "No configured Umuganda dates; confirm with RMS / RBC / MoH."
            elif feature == "national_commemoration_period" and not calendar_years:
                reason = "Commemoration dates are configuration-only and must be confirmed with RMS / RBC / MoH."
            elif feature.startswith("public_holiday_count") and not calendar_years:
                reason = "Holiday dates are configuration-only and must be confirmed with RMS / RBC / MoH."
            elif feature.startswith("periods_since_district_replenishment") and not self._district_replenishment_supplied:
                reason = "district_replenishment_date was not supplied."
            elif feature in OPTIONAL_ATTRIBUTES and feature not in self._optional_columns:
                reason = f"Optional input column '{feature}' was not present or populated in training data."
            reasons[feature] = reason
        return reasons

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        if not self._fitted:
            raise RuntimeError("FeatureBuilder.fit(train) must be called before transform(df)")
        data = normalize_periods(frame, self.frequency)
        for column in ("stock_on_hand", "units_consumed", "units_received"):
            if column not in data:
                raise ValueError(f"Feature input is missing '{column}'")
            data[column] = pd.to_numeric(data[column], errors="coerce")
        output: list[dict[str, object]] = []
        for _, group in data.groupby(["facility_id", "item_id"], sort=False):
            output.extend(self._transform_group(group))
        features = pd.DataFrame(output, columns=["facility_id", "item_id", "date", *self.feature_list, "is_synthetic"])
        features = features.sort_values(["facility_id", "item_id", "date"], kind="stable")
        features = indexed_by_observation(features.reset_index(drop=True))
        features.attrs["feature_availability"] = self.availability_report(features)
        features.attrs["feature_lineage"] = self.feature_lineage.copy()
        features.attrs["training_period_end"] = (
            self._training_period_end.start_time.isoformat()
            if self._training_period_end is not None
            else None
        )
        return features

    def _transform_group(self, group: pd.DataFrame) -> list[dict[str, object]]:
        records = group.to_dict(orient="records")
        period_map = {record["_period"]: index for index, record in enumerate(records)}
        stocks = [_number(record.get("stock_on_hand")) for record in records]
        consumption = [_number(record.get("units_consumed")) for record in records]
        receipts = [_number(record.get("units_received")) for record in records]
        historical_stock_medians = (
            pd.Series(stocks, dtype="float64").expanding(min_periods=1).median().to_numpy()
        )
        stockout_frame = pd.DataFrame(records)
        stockout = (
            stockout_frame["stock_out_days"].map(_number).gt(0).where(
                stockout_frame["stock_out_days"].map(_number).notna(),
                stockout_frame["stock_on_hand"].map(_number).eq(0),
            )
            if self.frequency == "monthly" and "stock_out_days" in stockout_frame
            else stockout_frame["stock_on_hand"].map(_number).eq(0)
        )
        if "stockout_flag" in stockout_frame:
            stockout = stockout | stockout_frame["stockout_flag"].map(
                lambda value: str(value).strip().casefold() == "true" or value is True
            )
        stockouts = stockout.fillna(False).astype(bool).tolist()
        calendar_years = self._calendar["_coverage_years"]
        result: list[dict[str, object]] = []
        previous_period: pd.Period | None = None
        zero_consumption_streak = 0
        last_receipt_period: pd.Period | None = None
        historical_stockout_count = 0
        last_stockout_period: pd.Period | None = None
        completed_stockout_duration_sum = 0
        completed_stockout_duration_count = 0
        active_stockout_duration = 0
        last_district_replenishment_period: pd.Period | None = None

        for index, record in enumerate(records):
            period = record["_period"]
            current_date = pd.Timestamp(record["date"]).date()
            contiguous = (
                previous_period is None
                or period.ordinal - previous_period.ordinal == 1
            )
            if not contiguous:
                if active_stockout_duration:
                    completed_stockout_duration_sum += active_stockout_duration
                    completed_stockout_duration_count += 1
                    active_stockout_duration = 0
                zero_consumption_streak = 0
            if np.isfinite(consumption[index]) and consumption[index] == 0:
                zero_consumption_streak += 1
            else:
                zero_consumption_streak = 0
            if np.isfinite(receipts[index]) and receipts[index] > 0:
                last_receipt_period = period
            if stockouts[index]:
                historical_stockout_count += 1
                last_stockout_period = period
                active_stockout_duration += 1
            elif active_stockout_duration:
                completed_stockout_duration_sum += active_stockout_duration
                completed_stockout_duration_count += 1
                active_stockout_duration = 0
            replenishment_date = record.get("district_replenishment_date")
            if replenishment_date is not None and str(replenishment_date).strip():
                replenishment_period = pd.Timestamp(replenishment_date).to_period(
                    "D" if self.frequency == "daily" else "M"
                )
                if replenishment_period <= period:
                    last_district_replenishment_period = replenishment_period
            row: dict[str, object] = {
                "facility_id": record["facility_id"],
                "item_id": record["item_id"],
                "date": pd.Timestamp(record["date"]),
                "is_synthetic": parse_boolean(record.get("is_synthetic")),
            }
            for window in self.windows:
                values = self._window_values(period, window, period_map, consumption)
                suffix = f"{window}_{self.unit}"
                statistics = (
                    ("mean", np.mean),
                    ("std", lambda values: np.std(values, ddof=1) if len(values) > 1 else float("nan")),
                    ("min", np.min),
                    ("max", np.max),
                )
                for name, statistic in statistics:
                    row[f"consumption_{name}_{suffix}"] = (
                        float(statistic(values)) if values is not None else float("nan")
                    )

            long_window = self.windows[-1]
            consumption_window = self._window_values(period, long_window, period_map, consumption)
            receipt_window = self._window_values(period, long_window, period_map, receipts)
            long_suffix = f"{long_window}_{self.unit}"
            if consumption_window is None:
                row[f"consumption_cv_{long_suffix}"] = float("nan")
                row[f"consumption_trend_slope_{long_suffix}"] = float("nan")
            else:
                mean_consumption = float(np.mean(consumption_window))
                std_consumption = float(np.std(consumption_window, ddof=1)) if len(consumption_window) > 1 else float("nan")
                row[f"consumption_cv_{long_suffix}"] = (
                    _safe_ratio(std_consumption, mean_consumption)
                )
                row[f"consumption_trend_slope_{long_suffix}"] = (
                    float(np.polyfit(np.arange(len(consumption_window)), consumption_window, 1)[0])
                    if len(consumption_window) > 1
                    else float("nan")
                )

            average = float(np.mean(consumption_window)) if consumption_window is not None else float("nan")
            row[self.cover_name] = _safe_ratio(stocks[index], average, self.cover_cap)
            reorder = _number(record.get("reorder_level"))
            row["stock_to_reorder_level_ratio"] = _safe_ratio(stocks[index], reorder)
            historical_stock_median = float(historical_stock_medians[index])
            row["stock_to_historical_median_ratio"] = _safe_ratio(stocks[index], historical_stock_median)
            row[f"consumption_zero_streak_{self.unit}"] = zero_consumption_streak
            row[f"periods_since_last_receipt_{self.unit}"] = (
                int(period.ordinal - last_receipt_period.ordinal)
                if last_receipt_period is not None
                else float("nan")
            )
            if receipt_window is None:
                row[f"receipt_frequency_{long_suffix}"] = float("nan")
                row[f"mean_receipt_size_{long_suffix}"] = float("nan")
                row[f"receipts_to_consumption_ratio_{long_suffix}"] = float("nan")
            else:
                positive_receipts = [value for value in receipt_window if value > 0]
                total_consumption = float(sum(consumption_window)) if consumption_window is not None else float("nan")
                row[f"receipt_frequency_{long_suffix}"] = len(positive_receipts) / long_window
                row[f"mean_receipt_size_{long_suffix}"] = (
                    float(np.mean(positive_receipts)) if positive_receipts else 0.0
                )
                row[f"receipts_to_consumption_ratio_{long_suffix}"] = (
                    _safe_ratio(float(sum(receipt_window)), total_consumption)
                )

            row["historical_stockout_count"] = historical_stockout_count
            row[f"periods_since_last_stockout_{self.unit}"] = (
                int(period.ordinal - last_stockout_period.ordinal)
                if last_stockout_period is not None
                else float("nan")
            )
            duration_sum = completed_stockout_duration_sum + active_stockout_duration
            duration_count = completed_stockout_duration_count + int(active_stockout_duration > 0)
            row[f"historical_stockout_duration_mean_{self.unit}"] = (
                duration_sum / duration_count if duration_count else 0.0
            )
            row[f"reporting_completeness_{long_suffix}"] = (
                sum(value in period_map for value in _window_periods(period, long_window)) / long_window
            )
            row["month"] = current_date.month
            row["rwanda_season"] = _season(current_date.month, self._calendar)
            if self.frequency == "daily":
                row["week_of_year"] = current_date.isocalendar().week
            row["umuganda_week"] = self._calendar_period_flag(
                period, current_date, self._calendar["umuganda_weeks"], calendar_years
            )
            if self.umuganda_rule_enabled:
                last_day = monthrange(current_date.year, current_date.month)[1]
                last_saturday = date(
                    current_date.year,
                    current_date.month,
                    last_day - ((date(current_date.year, current_date.month, last_day).weekday() - 5) % 7),
                )
                row["umuganda_week"] = current_date == last_saturday
            row["national_commemoration_period"] = self._calendar_period_flag(
                period,
                current_date,
                self._calendar["national_commemoration_periods"],
                calendar_years,
            )
            row[f"public_holiday_count_next_{self.horizon}_{self.unit}"] = self._holiday_count(
                period, calendar_years
            )
            row["quarter_end_period"] = (
                current_date.month in (3, 6, 9, 12)
                and (
                    self.frequency == "monthly"
                    or (current_date + timedelta(days=1)).month != current_date.month
                )
            )
            row[f"periods_since_district_replenishment_{self.unit}"] = (
                int(period.ordinal - last_district_replenishment_period.ordinal)
                if last_district_replenishment_period is not None
                else float("nan")
            )
            for column in self._optional_columns:
                value = record.get(column)
                row[column] = _number(value) if column in {
                    "catchment_population", "lead_time_days", "rainfall_anomaly", "temperature_anomaly"
                } else value
            for column in set(OPTIONAL_ATTRIBUTES).difference(self._optional_columns):
                row[column] = float("nan") if column in {
                    "catchment_population", "lead_time_days", "rainfall_anomaly", "temperature_anomaly"
                } else None
            for column in ("program_funded", "cold_chain", "outbreak_flag"):
                if column in self._optional_columns:
                    row[column] = parse_boolean(record.get(column))
            result.append(row)
            previous_period = period
        return result

    def _window_values(
        self,
        period: pd.Period,
        window: int,
        period_map: dict[pd.Period, int],
        values: list[float],
    ) -> list[float] | None:
        periods = _window_periods(period, window)
        positions = [period_map.get(value) for value in periods]
        if any(position is None for position in positions):
            return None
        selected = [values[int(position)] for position in positions if position is not None]
        return selected if all(np.isfinite(value) for value in selected) else None

    def _calendar_flag(
        self,
        value: date,
        ranges: list[dict[str, str]],
        coverage_years: set[int],
    ) -> bool | float:
        if value.year not in coverage_years and ranges:
            return float("nan")
        if not ranges:
            return False if value.year in coverage_years else float("nan")
        return _date_in_ranges(value, ranges)

    def _calendar_period_flag(
        self,
        period: pd.Period,
        value: date,
        ranges: list[dict[str, str]],
        coverage_years: set[int],
    ) -> bool | float:
        if self.frequency == "daily":
            return self._calendar_flag(value, ranges, coverage_years)
        month_start = period.start_time.date()
        month_end = period.end_time.date()
        if not any(year in coverage_years for year in range(month_start.year, month_end.year + 1)):
            return float("nan")
        return any(
            date.fromisoformat(item["start"]) <= month_end
            and date.fromisoformat(item["end"]) >= month_start
            for item in ranges
        )

    def _holiday_count(self, period: pd.Period, coverage_years: set[int]) -> int | float:
        if self.frequency == "daily":
            forecast_dates = [
                (period + offset).start_time.date()
                for offset in range(1, self.horizon + 1)
            ]
        else:
            forecast_dates = []
            for offset in range(1, self.horizon + 1):
                forecast_month = (period + offset)
                forecast_dates.extend(
                    pd.date_range(forecast_month.start_time, forecast_month.end_time, freq="D").date
                )
        if any(value.year not in coverage_years for value in forecast_dates):
            return float("nan")
        holidays = {date.fromisoformat(value) for value in self._calendar["public_holidays"]}
        return sum(value in holidays for value in forecast_dates)

    def availability_report(self, features: pd.DataFrame) -> dict[str, dict[str, object]]:
        total = len(features)
        report: dict[str, dict[str, object]] = {}
        for feature in self.feature_list:
            if feature not in features:
                available = 0
                reason = "Feature was not emitted by transform."
            else:
                available = int(features[feature].notna().sum())
                reason = self.feature_availability.get(feature)
            report[feature] = {
                "available_rows": available,
                "total_rows": total,
                "availability_share": available / total if total else None,
                "missing_reason": reason if available < total else None,
            }
        return report


__all__ = ["FeatureBuilder"]
