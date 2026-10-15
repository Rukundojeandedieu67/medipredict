"""Profile the four MediPredict training CSVs and enforce the join-coverage gate."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "datasets" / "medipredict_data" / "processed"
REPORT = ROOT / "docs" / "data_profile.md"
MAX_ALLOWED_JOIN_LOSS = 0.02

FILES = {
    "facility time series": PROCESSED / "medipredict_facility_timeseries_2026.csv",
    "master dataset": PROCESSED / "medipredict_master_rwanda_dataset.csv",
    "district climate": PROCESSED / "district_climate_rainfall.csv",
    "district census": PROCESSED / "nisr_census_2022_districts.csv",
}


def _pct(value: float) -> str:
    return f"{value:.4f}%"


def _profile_table(name: str, frame: pd.DataFrame, path: Path) -> list[str]:
    total_cells = frame.shape[0] * frame.shape[1]
    missing_cells = int(frame.isna().sum().sum())
    duplicate_rows = int(frame.duplicated().sum())
    explicit_flag = "is_synthetic" in frame.columns

    lines = [
        f"### {name}",
        "",
        f"- File: `{path.relative_to(ROOT).as_posix()}`",
        f"- Shape: {frame.shape[0]} rows × {frame.shape[1]} columns.",
        f"- Missing cells: {missing_cells}/{total_cells} ({_pct(100 * missing_cells / total_cells if total_cells else 0)}).",
        f"- Exact duplicate rows: {duplicate_rows}.",
        f"- `is_synthetic` column: {'present' if explicit_flag else 'absent'}; "
        + (
            f"true share {_pct(100 * frame['is_synthetic'].astype(str).str.casefold().isin(['true', '1']).mean())}."
            if explicit_flag
            else "explicit row-flag share is unavailable."
        ),
        "- Columns and pandas dtypes:",
        "",
        "| Column | Dtype | Missing | Missing % |",
        "|---|---|---:|---:|",
    ]
    for column in frame.columns:
        missing = int(frame[column].isna().sum())
        missing_pct = 100 * missing / len(frame) if len(frame) else 0
        lines.append(
            f"| `{column}` | `{frame[column].dtype}` | {missing} | {_pct(missing_pct)} |"
        )

    date_columns = [
        column
        for column in frame.columns
        if "date" in column.casefold()
        or column.casefold() == "month"
        or column.casefold().endswith("_month")
    ]
    if date_columns:
        lines.extend(["", "- Date coverage:"])
        for column in date_columns:
            parsed = pd.to_datetime(frame[column], errors="coerce")
            valid = parsed.dropna()
            if valid.empty:
                lines.append(f"  - `{column}`: no parseable dates.")
            else:
                lines.append(
                    f"  - `{column}`: {valid.min().date().isoformat()} through "
                    f"{valid.max().date().isoformat()} ({valid.nunique()} distinct parsed values)."
                )
    else:
        lines.extend(["", "- Date coverage: no date/month column."])
    lines.append("")
    return lines


def build_report() -> tuple[str, float, int, int]:
    frames: dict[str, pd.DataFrame] = {}
    for name, path in FILES.items():
        if not path.is_file():
            raise FileNotFoundError(f"Required profile input is missing: {path}")
        frames[name] = pd.read_csv(path, low_memory=False)

    ts = frames["facility time series"]
    master = frames["master dataset"]
    climate = frames["district climate"]
    census = frames["district census"]

    if not {"district", "reporting_month", "facility_name", "medicine_code"} <= set(ts.columns):
        raise ValueError("Facility time series is missing expected join/profile columns.")
    if "district" not in climate or "district" not in census or "district" not in master:
        raise ValueError("A district-based input is missing its district key.")

    matched_ts = ts.merge(climate[["district"]].drop_duplicates(), on="district", how="inner")
    join_loss = 1 - len(matched_ts) / len(ts) if len(ts) else 0
    ts_districts = set(ts["district"].dropna())
    census_districts = set(census["district"].dropna())
    climate_districts = set(climate["district"].dropna())
    master_districts = set(master["district"].dropna())

    grouped = ts.groupby(["facility_name", "medicine_code"], dropna=False).size()
    month_counts = ts.groupby("reporting_month", dropna=False).size().sort_index()
    climate_missing = sorted(ts_districts - climate_districts)
    census_spelling_mismatches = sorted(ts_districts ^ census_districts)
    master_spelling_mismatches = sorted(ts_districts ^ master_districts)

    lines = [
        "# MediPredict training data profile",
        "",
        "## Scope and gate",
        "",
        "Profiled only the four requested processed CSVs. No input was modified. "
        "No DHS PDF was read or used.",
        "",
        f"**STOP: the facility time-series → district climate inner join loses "
        f"{_pct(100 * join_loss)} of time-series rows** "
        f"({len(ts) - len(matched_ts)} of {len(ts)}; {len(matched_ts)} remain). "
        f"The allowed maximum is {_pct(100 * MAX_ALLOWED_JOIN_LOSS)}. "
        "Do not continue to target construction, model fitting, calibration, "
        "test metrics, or bundle export until rainfall coverage is repaired or "
        "the join strategy is explicitly changed and reviewed.",
        "",
        "## Per-file profile",
        "",
    ]
    for name, frame in frames.items():
        lines.extend(_profile_table(name, frame, FILES[name]))

    lines.extend(
        [
            "## Keys, coverage, and duplicate columns",
            "",
            "| Input | Candidate key / join key | Key coverage and cardinality |",
            "|---|---|---|",
            f"| Facility time series | `(facility_name, district, medicine_code, reporting_month)`; "
            f"facility-medicine groups `(facility_name, medicine_code)` | "
            f"{ts['facility_name'].nunique()} facilities; {ts['medicine_code'].nunique()} medicines; "
            f"{ts['reporting_month'].nunique()} months; "
            f"{len(grouped)} facility-medicine groups; rows/group sizes "
            f"{grouped.value_counts().sort_index().to_dict()}; "
            f"rows/month {month_counts.to_dict()} |",
            f"| Master dataset | `(district, medicine_code)` | "
            f"{master['district'].nunique()} districts; "
            f"{master[['district', 'medicine_code']].drop_duplicates().shape[0]} unique district-medicine keys |",
            f"| District climate | `district` | {len(climate_districts)} unique districts; "
            f"covers {len(climate_districts & ts_districts)}/{len(ts_districts)} time-series districts; "
            f"missing: {', '.join(climate_missing)} |",
            f"| District census | `district` | {len(census_districts)} unique districts; "
            f"covers {len(census_districts & ts_districts)}/{len(ts_districts)} time-series districts |",
            "",
            f"- District spelling mismatch, time series vs census: "
            f"{census_spelling_mismatches or 'none'}; match is exact and case-sensitive.",
            f"- District spelling mismatch, time series vs master: "
            f"{master_spelling_mismatches or 'none'}; match is exact and case-sensitive.",
            f"- District-key row coverage: time series → census "
            f"{len(ts.merge(census[['district']].drop_duplicates(), on='district', how='inner'))}/{len(ts)} rows; "
            f"master → census "
            f"{len(master.merge(census[['district']].drop_duplicates(), on='district', how='inner'))}/{len(master)} rows.",
            f"- Unique district-medicine key coverage: master → time series "
            f"{master[['district', 'medicine_code']].drop_duplicates().merge(ts[['district', 'medicine_code']].drop_duplicates(), on=['district', 'medicine_code'], how='inner').shape[0]}/"
            f"{master[['district', 'medicine_code']].drop_duplicates().shape[0]} master keys. "
            "A row-level join to facility observations is one-to-many and should not "
            "be used to duplicate master operational records across facilities.",
            f"- Month format: `{ts['reporting_month'].dtype}`, values use `YYYY-MM`; "
            f"coverage is `{ts['reporting_month'].min()}` through "
            f"`{ts['reporting_month'].max()}`.",
            "- No `reporting_month` or equivalent date key exists in the climate, "
            "master, or census CSVs. Climate can only be district-joined as a "
            "static snapshot; it cannot be joined as observed month-specific "
            "rainfall from these inputs.",
            "",
            "The master dataset repeats concepts already available from the other "
            "tables. If modeling proceeds after the coverage gate is resolved, "
            "use one source per concept:",
            "",
            "| Master column | Duplicate source column(s) | Single source to use |",
            "|---|---|---|",
            "| `district`, `province` | same columns in time series and census | district census for district/province reference; validate the time-series mapping |",
            "| `district_population_nisr` | `population_2022`; `nisr_district_population` | census `population_2022` |",
            "| `under_5_population_nisr` | `under_5_pop`; `nisr_under_5_population` | census `under_5_pop` |",
            "| `women_reproductive_age_nisr` | `women_15_49` | census `women_15_49` |",
            "| `poverty_headcount_pct_eicv` | `poverty_rate_pct`; `nisr_poverty_rate_pct` | census `poverty_rate_pct` |",
            "| `malaria_prevalence_pct_rdhs` | `malaria_prev_pct`; `nisr_malaria_prevalence_pct` | census `malaria_prev_pct` |",
            "| `medicine_code`, `medicine_name` | same columns in time series | time series medicine identifiers for facility-level modeling |",
            "| `avg_daily_consumption_units` | same column in time series | time-series value for the facility-month row; do not join the master value as a second consumption feature |",
            "| `current_stock_units`, `estimated_lead_time_days`, `predicted_risk_level`, `pending_depot_orders_units` | no same-named time-series fields; several are alternative generated operational measures | do not combine master operational values with facility-month observations |",
            "",
            "All four CSVs lack `is_synthetic`; consequently none has a computable "
            "explicit synthetic-flag share. Generator evidence establishes that "
            "the master and facility time-series tables contain generated stock/"
            "consumption observations in 100% of rows. Census values are hardcoded "
            "unverified seed values, not verified official data. The climate file "
            "contains one `4.5` value (Gasabo), matching the generator's failure "
            "fallback; without a row flag or retained API response, whether that "
            "row actually used the fallback cannot be proven from the CSV.",
            "",
            "## Leakage check (before modeling)",
            "",
            "`datasets/build_facility_timeseries.py` computes "
            "`lead_time_days_remaining = round(end_of_month_stock_units / "
            "avg_daily_consumption_units, 1)` and buckets that value into "
            "`stockout_risk_label` using thresholds `<7`, `7–14`, and `>14`. "
            "`datasets/download_and_build_medipredict_data.py` likewise computes "
            "`estimated_lead_time_days = round(current_stock / daily_consumption, 1)` "
            "and buckets it into `predicted_risk_level` at the same thresholds. "
            "Both labels are deterministic functions of same-row stock and "
            "consumption. They are leaked targets for a model given those "
            "features and must not be used as forward-looking targets.",
            "",
            "## Required stop; next action",
            "",
            "The rainfall join loses 84.0000% of time-series rows, exceeding the "
            "2% stop condition. No future target, feature matrix, time split, "
            "baseline/model, validation calibration, test metric, permutation "
            "importance, or serving artifact was created. First obtain or define "
            "a defensible rainfall coverage strategy for all 30 districts and "
            "rerun this profile. The current climate file has only 5 of 30 "
            "districts and no month key, so forward-looking monthly climate "
            "features cannot be established from it.",
            "",
        ]
    )
    return "\n".join(lines), join_loss, len(ts), len(matched_ts)


def main() -> None:
    report, join_loss, rows_before, rows_after = build_report()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(f"Wrote profile: {REPORT}")
    print(f"Time-series rows before climate join: {rows_before}")
    print(f"Time-series rows after climate join: {rows_after}")
    print(f"Climate join row loss: {_pct(100 * join_loss)}")
    if join_loss > MAX_ALLOWED_JOIN_LOSS:
        raise SystemExit(
            f"STOP: join loss exceeds the {_pct(100 * MAX_ALLOWED_JOIN_LOSS)} limit; "
            "do not continue to modeling."
        )


if __name__ == "__main__":
    main()
