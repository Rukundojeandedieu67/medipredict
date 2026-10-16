import pandas as pd
import pytest

from backend.app.validation import ValidationConfig, validate_inventory_csv


def _frame(rows=None) -> pd.DataFrame:
    if rows is None:
        rows = [
            {
                "facility_id": "FAC-1",
                "item_id": "ITEM-1",
                "date": "2026-01-01",
                "stock_on_hand": "20",
                "units_consumed": "2",
                "units_received": "0",
                "is_synthetic": "false",
            }
        ]
    return pd.DataFrame(rows)


def _codes(report, category="errors"):
    return {issue["code"] for issue in report[category]}


def test_reports_missing_required_columns():
    report = validate_inventory_csv(
        pd.DataFrame([{"facility_id": "FAC-1"}]),
        purpose="assessment",
    )

    assert "REQUIRED_COLUMN_MISSING" in _codes(report)
    assert report["valid"] is False


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("facility_id", "", "INVALID_IDENTIFIER"),
        ("item_id", "", "INVALID_IDENTIFIER"),
        ("date", "2026-1-01", "INVALID_DATE"),
        ("stock_on_hand", "NaN", "INVALID_NUMBER"),
        ("units_consumed", "-1", "NEGATIVE_VALUE"),
        ("units_received", "-0.5", "NEGATIVE_VALUE"),
        ("lead_time_days", "invalid", "INVALID_OPTIONAL_NUMBER"),
        ("facility_type", 123, "INVALID_TEXT"),
        ("is_synthetic", "unknown", "INVALID_BOOLEAN"),
        ("stockout_flag", "unknown", "INVALID_BOOLEAN"),
    ],
)
def test_reports_field_validation_errors(column, value, code):
    frame = _frame()
    if column not in frame.columns:
        frame[column] = pd.Series([value], index=frame.index, dtype=object)
    else:
        frame[column] = pd.Series([value], index=frame.index, dtype=object)

    report = validate_inventory_csv(frame, purpose="assessment")

    assert code in _codes(report)


def test_reports_duplicate_facility_item_date():
    frame = _frame([_frame().iloc[0].to_dict(), _frame().iloc[0].to_dict()])

    report = validate_inventory_csv(frame, purpose="assessment")

    assert "DUPLICATE_FACILITY_ITEM_DATE" in _codes(report)


def test_minimum_history_is_an_error_for_training_and_warning_for_assessment():
    frame = _frame()
    config = ValidationConfig(minimum_records_per_facility_item=2, minimum_facility_items=1)

    training = validate_inventory_csv(frame, purpose="training", config=config)
    assessment = validate_inventory_csv(frame, purpose="assessment", config=config)

    assert "MINIMUM_HISTORY_RECORDS" in _codes(training)
    assert "MINIMUM_HISTORY_RECORDS" in _codes(assessment, "warnings")
    assert "MINIMUM_FACILITY_ITEMS" not in _codes(training)


def test_minimum_distinct_facility_items_blocks_training():
    report = validate_inventory_csv(
        _frame(),
        purpose="training",
        config=ValidationConfig(minimum_records_per_facility_item=1, minimum_facility_items=2),
    )

    assert "MINIMUM_FACILITY_ITEMS" in _codes(report)


def test_reports_gap_chronology_and_consumption_anomaly_warnings():
    rows = [
        {
            "facility_id": "FAC-1",
            "item_id": "ITEM-1",
            "date": "2026-01-03",
            "stock_on_hand": "1",
            "units_consumed": "20",
            "units_received": "0",
            "is_synthetic": "false",
        },
        {
            "facility_id": "FAC-1",
            "item_id": "ITEM-1",
            "date": "2026-01-01",
            "stock_on_hand": "1",
            "units_consumed": "0",
            "units_received": "0",
            "is_synthetic": "false",
        },
    ]
    report = validate_inventory_csv(
        _frame(rows),
        purpose="assessment",
        config=ValidationConfig(minimum_records_per_facility_item=3, minimum_facility_items=2),
    )

    codes = _codes(report, "warnings")
    assert {
        "DATE_GAPS",
        "NON_CHRONOLOGICAL_ROWS",
        "CONSUMPTION_EXCEEDS_AVAILABLE_STOCK",
        "MINIMUM_HISTORY_RECORDS",
        "MINIMUM_FACILITY_ITEMS",
    }.issubset(codes)


def test_caps_returned_issues_and_reports_total_counts():
    rows = []
    for index in range(101):
        rows.append(
            {
                "facility_id": "",
                "item_id": f"ITEM-{index}",
                "date": "2026-01-01",
                "stock_on_hand": "1",
                "units_consumed": "0",
                "units_received": "0",
                "is_synthetic": "false",
            }
        )

    report = validate_inventory_csv(
        _frame(rows),
        purpose="assessment",
        config=ValidationConfig(max_returned_issues=100),
    )

    assert len(report["errors"]) == 100
    assert report["total_counts"]["errors"] == 101
    assert report["total_counts"]["errors_truncated"] is True
