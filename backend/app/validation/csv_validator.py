from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Any, Literal

import pandas as pd

REQUIRED_COLUMNS = (
    "facility_id",
    "item_id",
    "date",
    "stock_on_hand",
    "units_consumed",
    "units_received",
    "is_synthetic",
)
OPTIONAL_NUMERIC_COLUMNS = (
    "lead_time_days",
    "reorder_level",
    "stock_out_days",
    "catchment_population",
    "rainfall_anomaly",
    "temperature_anomaly",
    "reporting_completeness",
)
OPTIONAL_TEXT_COLUMNS = (
    "facility_type",
    "region",
    "district",
    "urban_rural",
    "item_category",
)
BOOLEAN_COLUMNS = (
    "is_synthetic",
    "stockout_flag",
    "program_funded",
    "cold_chain",
    "outbreak_flag",
)
MAX_RETURNED_ISSUES = 100


@dataclass(frozen=True)
class ValidationConfig:
    minimum_records_per_facility_item: int | None = None
    minimum_facility_items: int = 12
    consumption_to_available_warning_ratio: float = 2.0
    max_returned_issues: int = MAX_RETURNED_ISSUES
    data_frequency: Literal["daily", "monthly"] = "daily"

    def __post_init__(self) -> None:
        if self.minimum_records_per_facility_item is None:
            object.__setattr__(
                self,
                "minimum_records_per_facility_item",
                90 if self.data_frequency == "daily" else 24,
            )
        if self.minimum_records_per_facility_item < 1:
            raise ValueError("minimum_records_per_facility_item must be positive")
        if self.minimum_facility_items < 1:
            raise ValueError("minimum_facility_items must be positive")
        if self.consumption_to_available_warning_ratio <= 0:
            raise ValueError("consumption_to_available_warning_ratio must be positive")
        if not 1 <= self.max_returned_issues <= MAX_RETURNED_ISSUES:
            raise ValueError(f"max_returned_issues must be between 1 and {MAX_RETURNED_ISSUES}")
        if self.data_frequency not in ("daily", "monthly"):
            raise ValueError("data_frequency must be 'daily' or 'monthly'")


def _issue(row_number: int | None, column: str, code: str, message: str) -> dict[str, Any]:
    return {
        "row_number": row_number,
        "column": column,
        "code": code,
        "message": message,
    }


def _parse_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _parse_nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    try:
        parsed = datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return parsed if parsed.isoformat() == str(value).strip() else None


def _period_key(value: date, frequency: Literal["daily", "monthly"]) -> date:
    return value if frequency == "daily" else date(value.year, value.month, 1)


def _period_gap(left: date, right: date, frequency: Literal["daily", "monthly"]) -> int:
    if frequency == "daily":
        return (right - left).days
    return (right.year - left.year) * 12 + right.month - left.month


def validate_inventory_csv(
    frame: pd.DataFrame,
    *,
    purpose: Literal["assessment", "training"],
    config: ValidationConfig | None = None,
) -> dict[str, Any]:
    """Validate an uploaded inventory table without modifying the input frame."""
    settings = config or ValidationConfig()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    row_dates: dict[int, date] = {}
    numeric_values: dict[int, dict[str, float]] = {}
    parsed_pairs: dict[tuple[str, str], list[tuple[int, date]]] = {}
    parsed_synthetic: list[bool] = []

    def add(
        destination: list[dict[str, Any]],
        row_number: int | None,
        column: str,
        code: str,
        message: str,
    ) -> None:
        destination.append(_issue(row_number, column, code, message))

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    for column in missing:
        message = (
            "Column is_synthetic is required: true or false. "
            "Unknown data provenance is not accepted."
            if column == "is_synthetic"
            else f"Required column '{column}' is missing."
        )
        add(errors, 1, column, "REQUIRED_COLUMN_MISSING", message)

    if not missing:
        seen_keys: dict[tuple[str, str, date], int] = {}
        prior_dates: dict[tuple[str, str], date] = {}
        for position, (_, row) in enumerate(frame.iterrows()):
            row_number = position + 2
            identifiers: dict[str, str] = {}
            for column in ("facility_id", "item_id"):
                value = row[column]
                if not isinstance(value, str) or not value.strip():
                    add(errors, row_number, column, "INVALID_IDENTIFIER", "Value must be a non-empty string.")
                else:
                    identifiers[column] = value.strip()

            parsed_date = _parse_iso_date(row["date"])
            if parsed_date is None:
                add(errors, row_number, "date", "INVALID_DATE", "Date must use ISO YYYY-MM-DD format.")
            else:
                row_dates[position] = parsed_date

            numeric_values[position] = {}
            numeric_columns = ("stock_on_hand", "units_consumed", "units_received")
            for column in numeric_columns:
                value = _parse_nonnegative_number(row[column])
                if value is None:
                    raw_value = row[column]
                    try:
                        negative = float(raw_value) < 0
                    except (TypeError, ValueError):
                        negative = False
                    code = "NEGATIVE_VALUE" if negative else "INVALID_NUMBER"
                    message = (
                        "Value must be zero or greater."
                        if negative
                        else "Value must be a finite number."
                    )
                    add(errors, row_number, column, code, message)
                else:
                    numeric_values[position][column] = value

            for column in OPTIONAL_NUMERIC_COLUMNS:
                if column in frame.columns and str(row[column]).strip() != "":
                    value = _parse_nonnegative_number(row[column])
                    if value is None:
                        add(
                            errors,
                            row_number,
                            column,
                            "INVALID_OPTIONAL_NUMBER",
                            "Optional value must be a finite number greater than or equal to zero.",
                        )
                    else:
                        numeric_values[position][column] = value
                        if column == "stock_out_days":
                            maximum = (
                                1
                                if settings.data_frequency == "daily"
                                else (
                                    calendar.monthrange(parsed_date.year, parsed_date.month)[1]
                                    if parsed_date is not None
                                    else 31
                                )
                            )
                            if not value.is_integer() or value > maximum:
                                add(
                                    errors,
                                    row_number,
                                    column,
                                    "INVALID_STOCK_OUT_DAYS",
                                    f"Value must be a whole number from 0 to {maximum} for {settings.data_frequency} data.",
                                )
                        elif column == "reporting_completeness" and value > 1:
                            add(
                                errors,
                                row_number,
                                column,
                                "INVALID_OPTIONAL_NUMBER",
                                "Reporting completeness must be between 0 and 1.",
                            )

            if "district_replenishment_date" in frame.columns:
                raw_date = row["district_replenishment_date"]
                if str(raw_date).strip() != "" and _parse_iso_date(raw_date) is None:
                    add(
                        errors,
                        row_number,
                        "district_replenishment_date",
                        "INVALID_DATE",
                        "Date must use ISO YYYY-MM-DD format.",
                    )

            for column in OPTIONAL_TEXT_COLUMNS:
                if column in frame.columns and not isinstance(row[column], str):
                    add(errors, row_number, column, "INVALID_TEXT", "Optional value must be text.")

            for column in BOOLEAN_COLUMNS:
                if column in frame.columns:
                    parsed = _parse_boolean(row[column])
                    if parsed is None:
                        add(
                            errors,
                            row_number,
                            column,
                            "INVALID_BOOLEAN",
                            "Value must be true or false (case-insensitive).",
                        )
                    elif column == "is_synthetic":
                        parsed_synthetic.append(parsed)

            if set(identifiers) == {"facility_id", "item_id"} and parsed_date is not None:
                pair = (identifiers["facility_id"], identifiers["item_id"])
                parsed_pairs.setdefault(pair, []).append((position, parsed_date))
                period_key = _period_key(parsed_date, settings.data_frequency)
                key = (*pair, period_key)
                if key in seen_keys:
                    add(
                        errors,
                        row_number,
                        "facility_id,item_id,date",
                        "DUPLICATE_FACILITY_ITEM_DATE",
                        (
                            f"Duplicate of CSV row {seen_keys[key]} for this facility-item "
                            f"{settings.data_frequency} period."
                        ),
                    )
                else:
                    seen_keys[key] = row_number

                prior = prior_dates.get(pair)
                if prior is not None and parsed_date < prior:
                    add(
                        warnings,
                        row_number,
                        "date",
                        "NON_CHRONOLOGICAL_ROWS",
                        "Rows for this facility-item are not in chronological order.",
                    )
                prior_dates[pair] = parsed_date

            required_numbers = ("stock_on_hand", "units_consumed", "units_received")
            if all(column in numeric_values[position] for column in required_numbers):
                stock = numeric_values[position]["stock_on_hand"]
                consumed = numeric_values[position]["units_consumed"]
                received = numeric_values[position]["units_received"]
                available = stock + received
                if consumed > 0 and consumed > settings.consumption_to_available_warning_ratio * available:
                    add(
                        warnings,
                        row_number,
                        "units_consumed",
                        "CONSUMPTION_EXCEEDS_AVAILABLE_STOCK",
                        (
                            f"Consumption exceeds {settings.consumption_to_available_warning_ratio:g} "
                            "times stock on hand plus receipts."
                        ),
                    )

    for pair, observations in parsed_pairs.items():
        ordered_dates = sorted(set(_period_key(value, settings.data_frequency) for _, value in observations))
        gap_count = sum(
            max(_period_gap(left, right, settings.data_frequency) - 1, 0)
            for left, right in zip(ordered_dates, ordered_dates[1:])
        )
        if gap_count:
            next_date = next(
                right
                for left, right in zip(ordered_dates, ordered_dates[1:])
                if _period_gap(left, right, settings.data_frequency) > 1
            )
            next_position = next(
                position
                for position, value in observations
                if _period_key(value, settings.data_frequency) == next_date
            )
            add(
                warnings,
                next_position + 2,
                "date",
                "DATE_GAPS",
                (
                    f"{gap_count} {settings.data_frequency} period(s) are missing "
                    "within this facility-item history."
                ),
            )

        if len(observations) < settings.minimum_records_per_facility_item:
            first_position = min(position for position, _ in observations)
            destination = errors if purpose == "training" else warnings
            add(
                destination,
                first_position + 2,
                "facility_id,item_id",
                "MINIMUM_HISTORY_RECORDS",
                (
                    f"History has {len(observations)} record(s); at least "
                    f"{settings.minimum_records_per_facility_item} are required for training."
                ),
            )

    pair_count = len(parsed_pairs)
    if pair_count < settings.minimum_facility_items:
        destination = errors if purpose == "training" else warnings
        add(
            destination,
            None,
            "facility_id,item_id",
            "MINIMUM_FACILITY_ITEMS",
            (
                f"Dataset contains {pair_count} distinct facility-item pair(s); at least "
                f"{settings.minimum_facility_items} are required for training."
            ),
        )

    total_errors = len(errors)
    total_warnings = len(warnings)
    limit = settings.max_returned_issues
    valid = total_errors == 0
    return {
        "valid": valid,
        "purpose": purpose,
        "data_frequency": settings.data_frequency,
        "data_frequency": settings.data_frequency,
        "row_count": len(frame),
        "facility_item_count": pair_count,
        "errors": errors[:limit],
        "warnings": warnings[:limit],
        "total_counts": {
            "errors": total_errors,
            "warnings": total_warnings,
            "returned_errors": min(total_errors, limit),
            "returned_warnings": min(total_warnings, limit),
            "errors_truncated": total_errors > limit,
            "warnings_truncated": total_warnings > limit,
        },
        "date_range": {
            "start": min(row_dates.values()).isoformat() if row_dates else None,
            "end": max(row_dates.values()).isoformat() if row_dates else None,
        },
        "is_synthetic": (
            parsed_synthetic[0]
            if parsed_synthetic and all(value == parsed_synthetic[0] for value in parsed_synthetic)
            else None
        ),
    }
