from datetime import date

import pytest

from ml_engine.pipeline.refresh_climate_data import (
    _complete_monthly_rows,
    _parse_daily_response,
)


def test_complete_months_excludes_partial_month_and_requires_every_district_day():
    daily = {
        "A": {
            date(2026, 1, day): 1.0
            for day in range(1, 32)
        }
        | {
            date(2026, 2, day): 2.0
            for day in range(1, 29)
        }
        | {
            date(2026, 3, day): 5.0
            for day in range(1, 16)
        },
        "B": {
            date(2026, 1, day): 3.0
            for day in range(1, 32)
        }
        | {
            date(2026, 2, day): 4.0
            for day in range(1, 29)
            if day != 10
        }
        | {
            date(2026, 3, day): 5.0
            for day in range(1, 16)
        },
    }

    result, latest, excluded = _complete_monthly_rows(
        daily,
        date(2026, 1, 1),
        date(2026, 3, 15),
        "2026-03-16T00:00:00+00:00",
    )

    assert result[["district", "reporting_month", "monthly_rainfall_mm"]].to_dict(
        "records"
    ) == [
        {"district": "A", "reporting_month": "2026-01", "monthly_rainfall_mm": 31.0},
        {"district": "B", "reporting_month": "2026-01", "monthly_rainfall_mm": 93.0},
    ]
    assert result["is_complete_month"].all()
    assert not result["is_synthetic"].any()
    assert latest == date(2026, 3, 15)
    assert excluded == ["2026-02", "2026-03"]


def test_parse_daily_response_rejects_invalid_precipitation():
    with pytest.raises(RuntimeError, match="invalid precipitation"):
        _parse_daily_response(
            {
                "daily": {
                    "time": ["2026-01-01"],
                    "precipitation_sum": [-1],
                }
            },
            "Gasabo",
        )


def test_parse_daily_response_rejects_api_error():
    with pytest.raises(RuntimeError, match="service unavailable"):
        _parse_daily_response(
            {"error": True, "reason": "service unavailable"},
            "Gasabo",
        )
