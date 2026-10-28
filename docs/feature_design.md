# Point-in-time feature and label design

This phase builds dataset labels and features only. It does not train, choose, or promote a model, and it makes no performance claim.

## Native data frequency and horizon

`data_frequency` is either `daily` or `monthly`. It is recorded by the training-upload route and must match the setting used by dataset preparation. Dates remain ISO `YYYY-MM-DD`; monthly data has at most one observation per facility-item-month, with the supplied date serving as that month's report date. Validation defaults to at least 90 daily records or 24 monthly records per facility-item. Both are configurable. Twenty-four monthly periods are an operational minimum only; seasonality cannot be learned reliably with fewer than 36 monthly observations.

| Frequency | Default horizon | Supported meaning | Native windows |
|---|---:|---|---|
| Daily | 14 | Next 14 daily observations after the prediction date | 7, 14, and 28 days |
| Monthly | 1 | Next 1 or 2 monthly observations after the report date | 3, 6, and 12 months |

An explicit positive horizon can be selected for daily data. Monthly horizons are restricted to one or two months. No daily-only feature is calculated for monthly input. The feature builder rejects multiple observations for one facility-item-frequency period.

## Stock-out event definition and labels

- Daily event: `stock_on_hand == 0` or `stockout_flag == true`.
- Monthly event: `stock_out_days > 0` when that value is present; otherwise `stock_on_hand == 0`. A recorded `stockout_flag == true` also marks an event.
- A zero end-of-period stock used without an event field is a documented proxy assumption. It does not establish that a source system recorded the stock-out.
- Default `label_mode="new_stockout"` excludes rows already in a stock-out at time `t`. `any_stockout_in_window` permits those rows, but the window remains strictly `(t, t+H]`.
- `target=1` if any event is observed in the next H native periods; `target=0` only when all H periods are observed and none has an event.
- End-of-data rows with an incomplete horizon receive a null target and `label_status="unobserved_window"`. If a missing period interrupts the window, the target is null and `label_status="unobserved_period"`. No missing report is treated as a no-stock-out outcome.
- Under `new_stockout`, a row already in stock-out at `t` receives a null target and `label_status="excluded_current_stockout"`.

`ml.labels.label_prevalence` reports observed-row counts, positives, and prevalence overall and by facility type, district, and item. Groups absent from the source are omitted; missing group values are reported as `Unknown`.

## Feature definitions and point-in-time boundary

Every feature for row `t` is constructed from source observations at or before `t`. Window statistics include the current observation. A trailing rolling statistic is null unless every expected native period in its window is reported and has a numeric value. The feature builder operates on rows in time order and retains the `(facility_id, item_id, t)` key.

| Feature family | Daily | Monthly | Availability / safeguards |
|---|---|---|---|
| Consumption mean, sample standard deviation, minimum, maximum | 7/14/28 days | 3/6/12 months | Full contiguous trailing window required. |
| Consumption coefficient of variation and linear trend slope | 28-day window | 12-month window | Null when the full window is incomplete or mean consumption is zero. |
| Stock cover | `days_of_cover = stock / trailing mean consumption` | `months_of_stock = stock / trailing mean consumption` | Zero/non-positive denominator yields null. Results are capped at 365 days or 120 months; these are engineering caps, not operational thresholds. |
| Stock relative to reorder level and historical median | Ratio at `t` | Ratio at `t` | Null when denominator is absent or zero. The historical median includes observations only through `t`. |
| Consumption volatility and zero-consumption streak | Periods are days | Periods are months | Streak is broken by a non-zero value or a missing period. |
| Receipt features | Periods are days | Periods are months | Time since last receipt, receipt frequency, mean positive receipt size, and trailing receipts-to-consumption ratio use observations no later than `t`. |
| Stock-out history | Days | Months | Count, periods since last event, and mean observed stock-out run duration include no observations after `t`. |
| Lead time | `lead_time_days`, if supplied | `lead_time_days`, if supplied | Otherwise null and noted unavailable. |
| Calendar | Month, ISO week of year, Rwanda season, configured Umuganda/commemoration flags, configured public-holiday count over next H days, quarter-end-period flag | Month, Rwanda season, configured calendar flags, configured public-holiday count over next H months, quarter-end-period flag | Week of year is daily-only. Calendar flags remain null where calendar coverage has not been verified. |
| Replenishment | Periods since last district replenishment | Periods since last district replenishment | Uses `district_replenishment_date` only when supplied; otherwise null. |
| Facility/item attributes | Supplied `facility_type`, district, `urban_rural`, `catchment_population`, `item_category`, `program_funded`, `cold_chain` | Same | Missing optional columns are null and listed in feature availability. |
| Context signals | Supplied rainfall/temperature anomalies and outbreak flag | Same | Never derived or fabricated when absent. |
| Reporting completeness | Share of reported rows in trailing 28 daily periods | Share of reported rows in trailing 12 months | Computed from observations through `t`; initial partial history is reflected in the share. |

The Rwanda seasons in `ml/config/rwanda_calendar.json` follow the supplied definition: long rains March-May, short dry June-August, short rains September-November, and long dry December-February. Umuganda is computed as the last Saturday of each month while `umuganda_last_saturday_enabled` is true. For monthly reports, the flag becomes true only once the report date reaches that month's last Saturday. This rule's operational interpretation still requires confirmation with RMS / RBC / MoH. Calendar coverage years, national commemoration intervals, and public holidays are configuration-only and remain empty pending confirmed records; commemoration dates and holidays must be marked "to be confirmed with RMS / RBC / MoH" until sourced. Under 36 months of observations, seasonality cannot be learned reliably. Monthly history validation defaults to 24 periods per facility-item, configurable; seasonal features and the seasonal-naive baseline are disabled when the training history has fewer than 24 distinct monthly periods.

`FeatureBuilder.fit(train)` records the feature schema and categorical levels using only the training rows. It performs no imputation, scaling, or learned full-dataset statistics. `transform(df)` computes point-in-time features and preserves absent optional feature values as null. Any future encoder, scaler, or imputer must be separately fit only on training periods.

## Phase 4 training and evaluation

`python -m ml.train <feature-build-id>` accepts only a complete feature table produced by `ml.build_dataset`; the registered validation status, feature schema, source hash, frequency, horizon, and persisted split columns are mandatory. Training never reads the source upload or regenerates labels. Numeric median imputation, scaling, category imputation, and one-hot category levels are fit on the temporal training rows only. The fixed small validation search is logistic-regression `C` in `{0.1, 1, 10}` and HistGradientBoosting `min_samples_leaf` in `{10, 30}`; the seed defaults to `20261016`.

The chronological split comes from `ml.splits.time_based_split`, with at least H native periods purged at each boundary. The independent unseen-facility/district evaluation trains a separate estimator using only the grouped-training facilities, uses its chronological validation rows for calibration and threshold selection, and evaluates held-out groups separately. No row-level random split is used. The final temporal test set is accessed once after validation tuning, calibration, and threshold selection.

The daily rule baseline uses CRITICAL for fewer than 7 days of cover, MODERATE for 7 through 14 days, and STABLE above 14 days. Since monthly stock cover is in months, the monthly equivalent is CRITICAL below 0.25 months, MODERATE from 0.25 through 0.5 months, and STABLE above 0.5 months. The rule thresholds are configurable in the trainer. Logistic regression and HistGradientBoosting use identical temporal partitions. Persistence is based on a stock-out in the immediately previous observed period; a missing previous period is not treated as a stock-out. Seasonal naive uses the same-period-last-year event only when at least 24 distinct monthly training periods are available. The monthly training default requires at least 30 positives in each temporal split and 12 distinct facilities; both thresholds can be configured. Training refuses fewer than 24 distinct months regardless of the configured minimum.

The operating threshold maximizes validation recall while meeting a configurable precision target (default 0.5). Model and rule thresholds are independently selected on the same validation split and target. If no threshold meets the target, the fallback maximizes validation F1 and is explicitly marked `precision_target_attained=false`; test precision/recall are reported at the selected threshold, but `recall_at_fixed_precision` and `fixed_precision_target` are null. Promotion compares model and rule recall only when both validation thresholds attained the same precision target. Isotonic calibration is fit on validation predictions only when there are at least 20 positive and 20 negative validation examples; otherwise Platt scaling is used when both classes are present. Test reports include PR-AUC, ROC-AUC, Brier score, precision, recall, F1, recall at the saved fixed-precision operating point when attained, facility-cluster bootstrap intervals (at least 1,000 resamples), subgroups, and label prevalence. Subgroup minimum positives defaults to 5. Monthly lead time reports the share of stock-outs flagged at least one month ahead; this is coarse by design, and finer lead-time claims require daily data. `python -m ml.promote <artifact-metadata.json>` re-evaluates the recorded gate without changing the immutable artifact.

The feature-build report also profiles source missingness by facility-item. It counts missing report periods only within each pair's observed date range and reports explicit blank/NA cells separately; observed zero stock or consumption is never treated as missing. This is diagnostic only: it neither inserts rows nor imputes measurements. Current repository inventory time-series data is synthetic, so its reporting completeness is not evidence about real facility reporting. Facility-specific imputation must not be added until real reporting history is available and a train-only, validated strategy is approved.

`ml.synthetic` defaults to monthly output (72 periods, 24 facilities) and can emit daily output with `--frequency daily`. Both frequencies are generated from simulated daily demand, orders, receipt lead times, and stock balance; monthly stock-out days are aggregated from the simulated daily stock dynamics. Every row is marked `is_synthetic=true`. These fixtures exist only to test pipeline signal recovery and are never evidence of real-world performance.

Feature-table metadata records the exact `features.csv` SHA-256 and row count. Training verifies those values, the build ID, and a consistent row-level `is_synthetic` value before fitting. It recomputes temporal split assignments from dates and unseen-group assignments from group identifiers without consulting target values, validates the temporal row assignments and recorded boundaries, and requires at least H purged periods at both temporal boundaries. The time-split promotion criterion is set from this verification. Leakage diagnostics and train/validation summary checks use training and validation rows only; test labels are accessed only after model and rule thresholds/calibrators are frozen, and the stored test summary is checked during that single final pass. The rule threshold and model threshold are each selected on validation to meet the same configured precision target, and test precision/recall are reported for both.

Permutation importance is calculated on validation data. SHAP is reported only if it can be computed for the installed best-tree implementation; otherwise its absence and reason are recorded. Promotion requires non-synthetic data whose provenance status is `verified` and whose verified dataset hash exactly matches the source dataset hash, a time-based test, a positive clustered-bootstrap lower bound for PR-AUC improvement over the rule baseline, better recall at the selected operating point, Brier score no greater than 0.25, unseen-group recall within 0.10 of temporal recall, and no Phase 3 leakage warnings. Missing provenance metadata is treated as `uploaded_unverified`, so legacy and unverified artifacts cannot pass. These are explicit engineering gates, not claims that the thresholds are clinically or operationally validated. Synthetic datasets can never pass the promotion gate.

Artifacts are immutable versioned directories under `ml/models/`. Each contains the fitted estimators and calibrators, the serialized `FeatureBuilder.state_dict()` (feature schema, calendar configuration, training cutoff, availability, and lineage), metadata, and JSON/Markdown evaluation reports. Synthetic reports and metadata are labeled `SYNTHETIC - not evidence of real-world performance`. The Phase 4 models are not served by the API.

## Leakage diagnostics

- Future-invariance: changing all source rows after `t` must not change features at `t`.
- Labels retain their future interval `(t, t+H]`; feature lineage records a maximum future offset of zero.
- Every feature table is unique and keyed by `(facility_id, item_id, t)`.
- The target leakage diagnostic scans numeric features for absolute correlation greater than 0.95 on the supplied synthetic test set. The test fails if any feature crosses that threshold.
- A single-feature ROC-AUC diagnostic is reported only for leakage/trivial-rule screening, including `days_of_cover` / `months_of_stock`. Values above 0.95 are flagged as probable leakage or a trivial rule; they are not model performance metrics.
- A lineage entry sourced from `stock_on_hand` at `t+k` where `k > 0` emits a warning and is a leakage defect.

No target, label status, label window endpoint, or future-row measurement is included in the model feature list.

## Time split and unseen-group design

`ml.splits.time_based_split` sorts native periods chronologically. It assigns earlier periods to train, then validation, then test; it purges at least H complete periods between train/validation and validation/test. No random row-level shuffling is used. Returned split summaries include boundaries, row counts, positive counts, and label prevalence. The helper raises when any requested split has fewer than the configured minimum number of positives.

`ml.splits.grouped_unseen_split` independently holds out complete facilities or districts using deterministic group ordering. It reports disjoint train/test groups and the same row/positive/prevalence summaries, and raises if either side has too few positives. This is a split-design utility only; it does not evaluate a model.

## Registered-dataset builder

Run from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m ml.build_dataset <dataset-id>
```

The command reads the versioned `datasets/uploads/v1/<dataset-id>/` registry entry, verifies the recorded SHA-256, and reruns strict training validation. It refuses unregistered, modified, or invalid CSVs. Frequency defaults to the registry value; `--horizon`, `--label-mode`, and `--group-by` configure dataset construction.

The existing CSV assessment endpoint remains a daily-only rule-based estimate. Monthly data can be validated and prepared by this feature pipeline, but is rejected by assessment with HTTP 422 rather than being presented in day units.

Each successful run writes a unique versioned directory under `ml/artifacts/feature_tables/<dataset-id>/` containing `features.csv`, `metadata.json`, and `report.md`. The output preserves the row-level `is_synthetic` flag. A dataset containing any synthetic rows has the report title `SYNTHETIC - not evidence of real-world performance`. The metadata includes dataset hash, frequency, horizon, label mode, feature list and availability, split boundaries, prevalence, and allowed single-feature leakage diagnostics. No model training, selection, or evaluation occurs.

## Data provenance limitations

Current calendars, district replenishment dates, facility attributes, program flags, cold-chain status, climate anomalies, outbreak indicators, and reporting-completeness source fields are not established by this pipeline unless present in the uploaded source. Their absence yields nulls and is reported. Season definitions and operational calendars must be confirmed with RMS / Rwanda Biomedical Centre / MoH before operational use.
