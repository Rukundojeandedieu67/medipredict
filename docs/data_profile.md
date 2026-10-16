# MediPredict training data profile

## Scope and gate

Profiled the four requested processed CSVs and the supplemental monthly climate output. No input was modified. No DHS PDF was read or used. The original 5-row climate snapshot is retained and profiled for comparison; month-specific joins use the separate refreshed archive file when present.

Monthly climate refresh queried daily observations through 2026-10-14; last complete month in the monthly file is 2026-09. To refresh as new archive data becomes available, run `python ml_engine/pipeline/refresh_climate_data.py` from the repo root. The script requests through yesterday and emits only fully observed calendar months for all districts.

**STOP: the facility time-series → district climate inner join loses 10.0000% of time-series rows** (600 of 6000; 5400 remain). The allowed maximum is 2.0000%. Do not continue to target construction, model fitting, calibration, test metrics, or bundle export until rainfall coverage is repaired or the join strategy is explicitly changed and reviewed.

## Per-file profile

### facility time series

- File: `datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv`
- Shape: 6000 rows × 16 columns.
- Missing cells: 0/96000 (0.0000%).
- Exact duplicate rows: 0.
- `is_synthetic` column: absent; explicit row-flag share is unavailable.
- Columns and pandas dtypes:

| Column | Dtype | Missing | Missing % |
|---|---|---:|---:|
| `reporting_month` | `str` | 0 | 0.0000% |
| `facility_name` | `str` | 0 | 0.0000% |
| `facility_type` | `str` | 0 | 0.0000% |
| `district` | `str` | 0 | 0.0000% |
| `province` | `str` | 0 | 0.0000% |
| `nisr_district_population` | `int64` | 0 | 0.0000% |
| `nisr_under_5_population` | `int64` | 0 | 0.0000% |
| `nisr_poverty_rate_pct` | `float64` | 0 | 0.0000% |
| `nisr_malaria_prevalence_pct` | `float64` | 0 | 0.0000% |
| `medicine_code` | `str` | 0 | 0.0000% |
| `medicine_name` | `str` | 0 | 0.0000% |
| `end_of_month_stock_units` | `int64` | 0 | 0.0000% |
| `avg_daily_consumption_units` | `int64` | 0 | 0.0000% |
| `lead_time_days_remaining` | `float64` | 0 | 0.0000% |
| `stockout_risk_label` | `str` | 0 | 0.0000% |
| `rainy_season_active` | `int64` | 0 | 0.0000% |

- Date coverage:
  - `reporting_month`: 2026-01-01 through 2026-10-01 (10 distinct parsed values).

### master dataset

- File: `datasets/medipredict_data/processed/medipredict_master_rwanda_dataset.csv`
- Shape: 120 rows × 17 columns.
- Missing cells: 0/2040 (0.0000%).
- Exact duplicate rows: 0.
- `is_synthetic` column: absent; explicit row-flag share is unavailable.
- Columns and pandas dtypes:

| Column | Dtype | Missing | Missing % |
|---|---|---:|---:|
| `district` | `str` | 0 | 0.0000% |
| `province` | `str` | 0 | 0.0000% |
| `district_population_nisr` | `int64` | 0 | 0.0000% |
| `under_5_population_nisr` | `int64` | 0 | 0.0000% |
| `women_reproductive_age_nisr` | `int64` | 0 | 0.0000% |
| `poverty_headcount_pct_eicv` | `float64` | 0 | 0.0000% |
| `mutuelle_coverage_pct_eicv` | `float64` | 0 | 0.0000% |
| `malaria_prevalence_pct_rdhs` | `float64` | 0 | 0.0000% |
| `medicine_code` | `str` | 0 | 0.0000% |
| `medicine_name` | `str` | 0 | 0.0000% |
| `unit` | `str` | 0 | 0.0000% |
| `current_stock_units` | `int64` | 0 | 0.0000% |
| `avg_daily_consumption_units` | `int64` | 0 | 0.0000% |
| `estimated_lead_time_days` | `float64` | 0 | 0.0000% |
| `predicted_risk_level` | `str` | 0 | 0.0000% |
| `pending_depot_orders_units` | `int64` | 0 | 0.0000% |
| `data_source_verification` | `str` | 0 | 0.0000% |

- Date coverage: no date/month column.

### district climate

- File: `datasets/medipredict_data/processed/district_climate_monthly.csv`
- Shape: 270 rows × 9 columns.
- Missing cells: 0/2430 (0.0000%).
- Exact duplicate rows: 0.
- `is_synthetic` column: present; true share 0.0000%.
- Columns and pandas dtypes:

| Column | Dtype | Missing | Missing % |
|---|---|---:|---:|
| `district` | `str` | 0 | 0.0000% |
| `reporting_month` | `str` | 0 | 0.0000% |
| `monthly_rainfall_mm` | `float64` | 0 | 0.0000% |
| `days_observed` | `int64` | 0 | 0.0000% |
| `is_complete_month` | `bool` | 0 | 0.0000% |
| `latest_observed_date` | `str` | 0 | 0.0000% |
| `data_source` | `str` | 0 | 0.0000% |
| `retrieved_at_utc` | `str` | 0 | 0.0000% |
| `is_synthetic` | `bool` | 0 | 0.0000% |

- Date coverage:
  - `reporting_month`: 2026-01-01 through 2026-09-01 (9 distinct parsed values).
  - `latest_observed_date`: 2026-10-14 through 2026-10-14 (1 distinct parsed values).

### original district climate snapshot

- File: `datasets/medipredict_data/processed/district_climate_rainfall.csv`
- Shape: 5 rows × 2 columns.
- Missing cells: 0/10 (0.0000%).
- Exact duplicate rows: 0.
- `is_synthetic` column: absent; explicit row-flag share is unavailable.
- Columns and pandas dtypes:

| Column | Dtype | Missing | Missing % |
|---|---|---:|---:|
| `district` | `str` | 0 | 0.0000% |
| `weekly_avg_rainfall_mm` | `float64` | 0 | 0.0000% |

- Date coverage: no date/month column.

### district census

- File: `datasets/medipredict_data/processed/nisr_census_2022_districts.csv`
- Shape: 30 rows × 9 columns.
- Missing cells: 0/270 (0.0000%).
- Exact duplicate rows: 0.
- `is_synthetic` column: absent; explicit row-flag share is unavailable.
- Columns and pandas dtypes:

| Column | Dtype | Missing | Missing % |
|---|---|---:|---:|
| `province` | `str` | 0 | 0.0000% |
| `district` | `str` | 0 | 0.0000% |
| `population_2022` | `int64` | 0 | 0.0000% |
| `under_5_pop` | `int64` | 0 | 0.0000% |
| `women_15_49` | `int64` | 0 | 0.0000% |
| `poverty_rate_pct` | `float64` | 0 | 0.0000% |
| `mutuelle_pct` | `float64` | 0 | 0.0000% |
| `malaria_prev_pct` | `float64` | 0 | 0.0000% |
| `delivery_facility_pct` | `float64` | 0 | 0.0000% |

- Date coverage: no date/month column.

## Keys, coverage, and duplicate columns

| Input | Candidate key / join key | Key coverage and cardinality |
|---|---|---|
| Facility time series | `(facility_name, district, medicine_code, reporting_month)`; facility-medicine groups `(facility_name, medicine_code)` | 150 facilities; 4 medicines; 10 months; 600 facility-medicine groups; rows/group sizes {10: 600}; rows/month {'2026-01': 600, '2026-02': 600, '2026-03': 600, '2026-04': 600, '2026-05': 600, '2026-06': 600, '2026-07': 600, '2026-08': 600, '2026-09': 600, '2026-10': 600} |
| Master dataset | `(district, medicine_code)` | 30 districts; 120 unique district-medicine keys |
| District climate | `district, reporting_month` | 30 unique districts; covers 30/30 time-series districts; 9 months; missing districts: none; missing months: 2026-10 |
| District census | `district` | 30 unique districts; covers 30/30 time-series districts |

- District spelling mismatch, time series vs census: none; match is exact and case-sensitive.
- District spelling mismatch, time series vs master: none; match is exact and case-sensitive.
- District-key row coverage: time series → census 6000/6000 rows; master → census 120/120 rows.
- Unique district-medicine key coverage: master → time series 120/120 master keys. A row-level join to facility observations is one-to-many and should not be used to duplicate master operational records across facilities.
- Month format: `str`, values use `YYYY-MM`; coverage is `2026-01` through `2026-10`.
- Climate has a `reporting_month` key and is joined by both `district` and `reporting_month`.

The master dataset repeats concepts already available from the other tables. If modeling proceeds after the coverage gate is resolved, use one source per concept:

| Master column | Duplicate source column(s) | Single source to use |
|---|---|---|
| `district`, `province` | same columns in time series and census | district census for district/province reference; validate the time-series mapping |
| `district_population_nisr` | `population_2022`; `nisr_district_population` | census `population_2022` |
| `under_5_population_nisr` | `under_5_pop`; `nisr_under_5_population` | census `under_5_pop` |
| `women_reproductive_age_nisr` | `women_15_49` | census `women_15_49` |
| `poverty_headcount_pct_eicv` | `poverty_rate_pct`; `nisr_poverty_rate_pct` | census `poverty_rate_pct` |
| `malaria_prevalence_pct_rdhs` | `malaria_prev_pct`; `nisr_malaria_prevalence_pct` | census `malaria_prev_pct` |
| `medicine_code`, `medicine_name` | same columns in time series | time series medicine identifiers for facility-level modeling |
| `avg_daily_consumption_units` | same column in time series | time-series value for the facility-month row; do not join the master value as a second consumption feature |
| `current_stock_units`, `estimated_lead_time_days`, `predicted_risk_level`, `pending_depot_orders_units` | no same-named time-series fields; several are alternative generated operational measures | do not combine master operational values with facility-month observations |

All four CSVs lack `is_synthetic`; consequently none has a computable explicit synthetic-flag share. Generator evidence establishes that the master and facility time-series tables contain generated stock/consumption observations in 100% of rows. Census values are hardcoded unverified seed values, not verified official data. The climate file contains one `4.5` value (Gasabo), matching the generator's failure fallback; without a row flag or retained API response, whether that row actually used the fallback cannot be proven from the CSV.

## Leakage check (before modeling)

`datasets/build_facility_timeseries.py` computes `lead_time_days_remaining = round(end_of_month_stock_units / avg_daily_consumption_units, 1)` and buckets that value into `stockout_risk_label` using thresholds `<7`, `7–14`, and `>14`. `datasets/download_and_build_medipredict_data.py` likewise computes `estimated_lead_time_days = round(current_stock / daily_consumption, 1)` and buckets it into `predicted_risk_level` at the same thresholds. Both labels are deterministic functions of same-row stock and consumption. They are leaked targets for a model given those features and must not be used as forward-looking targets.

## Required stop; next action

The rainfall join loses 10.0000% of time-series rows, exceeding the 2.0000% stop condition. No future target, feature matrix, time split, baseline/model, validation calibration, test metric, permutation importance, or serving artifact was created. First obtain or define complete rainfall coverage for the time-series months and rerun this profile. Partial calendar months are excluded from the new archive output.
