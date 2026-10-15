"""Download complete monthly historical rainfall for Rwanda's districts."""

from __future__ import annotations

import argparse
import calendar
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "datasets" / "medipredict_data" / "processed"
CENSUS_PATH = PROCESSED / "nisr_census_2022_districts.csv"
TIMESERIES_PATH = PROCESSED / "medipredict_facility_timeseries_2026.csv"
OUTPUT_PATH = PROCESSED / "district_climate_monthly.csv"
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
TIMEZONE = "Africa/Kigali"
SOURCE_NAME = "Open-Meteo Historical Weather API"

# District-center coordinates (latitude, longitude).
DISTRICT_CENTERS = {
    "Gasabo": (-1.88, 30.13),
    "Kicukiro": (-1.98, 30.10),
    "Nyarugenge": (-1.95, 30.05),
    "Gisagara": (-2.62, 29.84),
    "Huye": (-2.59, 29.74),
    "Kamonyi": (-1.99, 29.90),
    "Muhanga": (-2.08, 29.75),
    "Nyamagabe": (-2.38, 29.47),
    "Nyanza": (-2.35, 29.75),
    "Nyaruguru": (-2.72, 29.52),
    "Ruhango": (-2.22, 29.78),
    "Karongi": (-2.15, 29.35),
    "Ngororero": (-1.86, 29.62),
    "Nyabihu": (-1.65, 29.50),
    "Nyamasheke": (-2.35, 29.15),
    "Rubavu": (-1.68, 29.26),
    "Rusizi": (-2.48, 28.90),
    "Rutsiro": (-1.93, 29.32),
    "Burera": (-1.48, 29.82),
    "Gakenke": (-1.70, 29.78),
    "Gicumbi": (-1.58, 30.06),
    "Musanze": (-1.50, 29.63),
    "Rulindo": (-1.73, 30.00),
    "Bugesera": (-2.21, 30.14),
    "Gatsibo": (-1.60, 30.45),
    "Kayonza": (-1.85, 30.65),
    "Kirehe": (-2.26, 30.65),
    "Ngoma": (-2.17, 30.53),
    "Nyagatare": (-1.30, 30.32),
    "Rwamagana": (-1.95, 30.43),
}


def _month_start(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.day != 1:
        raise ValueError(f"Start date must be the first of a month: {value}")
    return parsed


def _parse_daily_response(payload: dict[str, Any], district: str) -> dict[date, float | None]:
    if payload.get("error"):
        raise RuntimeError(f"Open-Meteo returned an error for {district}: {payload.get('reason')}")
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise RuntimeError(f"Open-Meteo response for {district} has no daily data.")
    dates = daily.get("time")
    rainfall = daily.get("precipitation_sum")
    if not isinstance(dates, list) or not isinstance(rainfall, list) or len(dates) != len(rainfall):
        raise RuntimeError(f"Open-Meteo response for {district} has mismatched daily arrays.")

    result: dict[date, float | None] = {}
    for date_value, rainfall_value in zip(dates, rainfall):
        day = date.fromisoformat(date_value)
        if day in result:
            raise RuntimeError(f"Open-Meteo returned duplicate date {day} for {district}.")
        if rainfall_value is None:
            result[day] = None
        elif isinstance(rainfall_value, (int, float)) and rainfall_value >= 0:
            result[day] = float(rainfall_value)
        else:
            raise RuntimeError(
                f"Open-Meteo returned invalid precipitation for {district} on {day}: "
                f"{rainfall_value!r}"
            )
    return result


def _complete_monthly_rows(
    daily_by_district: dict[str, dict[date, float | None]],
    start_date: date,
    requested_end_date: date,
    retrieved_at_utc: str,
) -> tuple[pd.DataFrame, date | None, list[str]]:
    if start_date.day != 1:
        raise ValueError("The requested start date must be the first day of a month.")
    if requested_end_date < start_date:
        raise ValueError("The requested end date precedes the start date.")

    latest_valid_dates = [
        max(day for day, amount in observations.items() if amount is not None)
        for observations in daily_by_district.values()
        if any(amount is not None for amount in observations.values())
    ]
    latest_common_observation = (
        min(latest_valid_dates) if len(latest_valid_dates) == len(daily_by_district) else None
    )

    months: list[tuple[date, date, int]] = []
    current = start_date
    while current <= requested_end_date:
        month_end = date(
            current.year,
            current.month,
            calendar.monthrange(current.year, current.month)[1],
        )
        expected_days = (month_end - current).days + 1
        months.append((current, month_end, expected_days))
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)

    rows: list[dict[str, Any]] = []
    excluded_months: list[str] = []
    for month_start, month_end, expected_days in months:
        month_dates = [
            date.fromordinal(month_start.toordinal() + offset)
            for offset in range(expected_days)
        ]
        if month_end > requested_end_date:
            excluded_months.append(month_start.strftime("%Y-%m"))
            continue

        month_values: dict[str, float] = {}
        for district, observations in daily_by_district.items():
            values = [observations.get(day) for day in month_dates]
            if len(values) != expected_days or any(value is None for value in values):
                break
            month_values[district] = sum(value for value in values if value is not None)
        if len(month_values) != len(daily_by_district):
            excluded_months.append(month_start.strftime("%Y-%m"))
            continue

        for district in sorted(daily_by_district):
            rows.append(
                {
                    "district": district,
                    "reporting_month": month_start.strftime("%Y-%m"),
                    "monthly_rainfall_mm": round(month_values[district], 1),
                    "days_observed": expected_days,
                    "is_complete_month": True,
                    "data_source": SOURCE_NAME,
                    "retrieved_at_utc": retrieved_at_utc,
                    "is_synthetic": False,
                }
            )

    return pd.DataFrame(rows), latest_common_observation, excluded_months


def _fetch_daily(
    district: str, latitude: float, longitude: float, start_date: date, end_date: date
) -> dict[date, float | None]:
    params = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": "precipitation_sum",
            "timezone": TIMEZONE,
        }
    )
    request = Request(
        f"{ARCHIVE_API}?{params}",
        headers={"User-Agent": "MediPredict climate data refresh/1.0"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Open-Meteo request failed for {district}: {error}") from error
    return _parse_daily_response(payload, district)


def _default_start_date() -> date:
    if not TIMESERIES_PATH.is_file():
        raise FileNotFoundError(f"Required facility time series is missing: {TIMESERIES_PATH}")
    months = pd.read_csv(TIMESERIES_PATH, usecols=["reporting_month"])["reporting_month"]
    parsed = pd.to_datetime(months, format="%Y-%m", errors="raise")
    return parsed.min().date().replace(day=1)


def refresh(
    start_date: date,
    requested_end_date: date,
    output_path: Path = OUTPUT_PATH,
) -> tuple[int, date | None, list[str]]:
    if not CENSUS_PATH.is_file():
        raise FileNotFoundError(f"Required district census file is missing: {CENSUS_PATH}")
    census_districts = set(pd.read_csv(CENSUS_PATH, usecols=["district"])["district"])
    if census_districts != set(DISTRICT_CENTERS):
        missing = sorted(census_districts - set(DISTRICT_CENTERS))
        extra = sorted(set(DISTRICT_CENTERS) - census_districts)
        raise ValueError(
            f"District-coordinate mismatch; missing coordinates={missing}, "
            f"unknown coordinates={extra}"
        )

    retrieved_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    daily_by_district = {
        district: _fetch_daily(district, latitude, longitude, start_date, requested_end_date)
        for district, (latitude, longitude) in DISTRICT_CENTERS.items()
    }
    monthly, latest_observation, excluded_months = _complete_monthly_rows(
        daily_by_district,
        start_date,
        requested_end_date,
        retrieved_at_utc,
    )
    if monthly.empty:
        raise RuntimeError(
            "Open-Meteo returned no fully observed calendar months for all districts; "
            "no output was written."
        )

    expected_rows = len(DISTRICT_CENTERS) * monthly["reporting_month"].nunique()
    if len(monthly) != expected_rows:
        raise RuntimeError(
            f"Monthly output is incomplete: {len(monthly)} rows, expected {expected_rows}; "
            "no output was written."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(output_path, index=False)
    return len(monthly), latest_observation, excluded_months


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-date",
        type=_month_start,
        default=None,
        help="First day of the first requested month; defaults to the time-series start month.",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=date.today() - timedelta(days=1),
        help="Last fully completed day to request; defaults to yesterday.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    start_date = args.start_date or _default_start_date()

    row_count, latest_observation, excluded_months = refresh(
        start_date,
        args.end_date,
        args.output.resolve(),
    )
    print(f"Wrote {row_count} fully observed district-month rows to {args.output.resolve()}")
    print(f"Last requested day: {args.end_date.isoformat()}")
    print(
        "Latest date with non-null observations across all districts: "
        + (latest_observation.isoformat() if latest_observation else "none")
    )
    print(
        "Excluded incomplete or unavailable months: "
        + (", ".join(excluded_months) if excluded_months else "none")
    )
    print("Synthetic rows: 0; all output rows have is_synthetic=false.")


if __name__ == "__main__":
    main()
