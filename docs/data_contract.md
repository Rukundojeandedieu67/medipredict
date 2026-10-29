# Inventory observation CSV contract

This contract applies to CSV validation, assessment, and restricted training-data intake. A valid training upload stores the source and metadata, then queues a candidate-training job; candidates are not automatically promoted or served. `data_frequency` is configured as `daily` or `monthly`; the default is `daily`.

## Required columns

| Column | Type and format | Allowed values / units |
|---|---|---|
| `facility_id` | Non-empty text identifier | Stable facility identifier; not a facility display name unless that name is the source identifier. |
| `item_id` | Non-empty text identifier | Stable medicine/item identifier. |
| `date` | ISO calendar date text, exactly `YYYY-MM-DD` | One observation date per facility-item per day, or one reported observation date in each monthly period. |
| `stock_on_hand` | Finite number | Count of stock units on hand at the reported date; zero or greater. |
| `units_consumed` | Finite number | Stock units consumed for the reported daily or monthly reporting period; zero or greater. |
| `units_received` | Finite number | Stock units received for the reported daily or monthly reporting period; zero or greater. |
| `is_synthetic` | Optional boolean text or boolean | Set to `true` for synthetic records. If omitted or blank, synthetic status remains unknown and the upload is treated as uploaded; the system does not assume `false`. |

The CSV does not encode a universal package unit. `stock_on_hand`, `units_consumed`, `units_received`, and `reorder_level` must use the same item-specific unit consistently. `units_consumed` and `units_received` represent the quantities recorded for that row's date. `lead_time_days` is measured in days.

## Optional columns

| Column | Type and format | Allowed values / units |
|---|---|---|
| `stockout_flag` | Boolean text or boolean | `true` or `false`, case-insensitive. |
| `stock_out_days` | Whole number | Daily: 0 or 1. Monthly: 0 through the number of calendar days in that month. For monthly labels, a positive value means a stock-out occurred during that month. |
| `lead_time_days` | Finite number | Zero or greater; days. |
| `reorder_level` | Finite number | Zero or greater; same stock unit as `stock_on_hand`. |
| `facility_type` | Text | Facility category as supplied by the source. |
| `region`, `district` | Text | Source-defined administrative area; preserve the supplied spelling. |
| `urban_rural`, `item_category` | Text | Source-provided facility context and medicine class. |
| `catchment_population`, `rainfall_anomaly`, `temperature_anomaly` | Finite number | Source-provided population count or anomaly in the source's documented units. |
| `program_funded`, `cold_chain`, `outbreak_flag` | Boolean text or boolean | `true` or `false`, case-insensitive. |
| `reporting_completeness` | Number from 0 to 1 | Optional source-provided completeness share; the feature pipeline independently computes trailing-window reporting completeness from observed periods. |
| `district_replenishment_date` | ISO calendar date text, exactly `YYYY-MM-DD` | Source-provided district replenishment date. |

Daily stock-out observation: `stock_on_hand == 0` or a recorded `stockout_flag=true`. Monthly stock-out observation: `stock_out_days > 0` when supplied; otherwise `stock_on_hand == 0`. If `stockout_flag` is supplied, `true` also records an event. Using zero end-of-period stock where no direct stock-out field is provided is a documented assumption, not proof of a recorded stock-out.

For the current assessment only, a zero `units_consumed` value produces `lead_time_days=null` and a `STABLE` rule tier because days of cover cannot be calculated from zero observed consumption. This is an operational convention, not a forecast.

## Validation rules

- A facility-item-period key must be unique at the configured frequency.
- Dates must parse exactly as `YYYY-MM-DD`. Rows are expected in chronological order within each facility-item group; ordering violations are warnings.
- Negative stock, consumption, or receipts are blocking errors.
- A record is warned when `units_consumed` is greater than two times `stock_on_hand + units_received`. This ratio is a configurable anomaly-screening heuristic, not a domain-validated threshold.
- Missing daily or monthly periods between observations are reported as gap warnings.
- Feature-dataset reports separately count absent periods between each facility-item's first and last observed date and explicit blank/NA values. Zero stock/consumption is observed data, not missingness. The profile does not insert rows or impute values; synthetic input is clearly marked and cannot be used to infer real facility reporting completeness.
- `stock_out_days` must be a whole number from 0 to 1 for daily data or 0 through the actual calendar-day count of the month for monthly data.
- Training intake requires configurable minimum history: **90 records per facility-item and 12 distinct facility-item pairs** by default. These counts are periods at the configured frequency and are validation thresholds, not evidence that a model can be trained or is valid. Assessment reports short history as warnings.
- Row-level error and warning lists are capped independently at 100 returned issues. Total counts and truncation flags are included in each validation report.

Configuration uses `MEDIPREDICT_TRAINING_MIN_RECORDS` and `MEDIPREDICT_TRAINING_MIN_FACILITY_ITEMS`.
The API-side frequency is configured with `MEDIPREDICT_DATA_FREQUENCY=daily|monthly`. Dataset preparation may set the frequency explicitly but it must match the value saved in the training-upload registry.

## Endpoint behavior

- `POST /api/v1/data/assess-csv` validates with assessment thresholds and returns a rule-based days-of-cover assessment for daily data only. Monthly data receives HTTP 422 rather than a misleading day-based estimate. A successful assessment stores the submitted CSV and SHA-256-checked metadata in configured object storage; it does not replace the dashboard snapshot, update inventory database rows, or train a model.
- `POST /api/v1/data/validate-csv?purpose=assessment|training` returns the validator report only.
- `POST /api/v1/data/training-upload` requires `X-Admin-API-Key`, stores a strictly validated CSV and its SHA-256/provenance metadata, and queues candidate training. The response includes `training_status: "queued"`; the job status can be checked separately. It does not promote or serve the candidate.
- `GET /api/v1/data/datasets/{dataset_id}/training-status` requires `X-Admin-API-Key` and returns the queued/running/completed/failed status and candidate details when available.
- `GET /api/v1/data/datasets`, `GET /api/v1/data/datasets/{dataset_id}`, and `GET /api/v1/data/datasets/{dataset_id}/provenance` require the admin key and expose derived provenance.
- `GET /api/v1/data/datasets/{dataset_id}/download` requires the admin key and returns the registered source CSV only after checking its SHA-256 against registry metadata.
- `GET /api/v1/data/archives`, `GET /api/v1/data/archives/{archive_id}/download`, and `GET /api/v1/data/archives/{archive_id}/manifest` list and retrieve the byte-preserving dashboard CSV archive and its SHA-256-checked manifest. The archive is explicitly labeled synthetic and is not training-eligible.
- `GET /api/v1/models` lists registered candidate metadata. `GET /api/v1/models/{model_version}/artifacts` and `GET /api/v1/models/{model_version}/features` retrieve the candidate and feature ZIP bundles after SHA-256 verification. These endpoints do not enable model serving.
- `POST /api/v1/data/datasets/{dataset_id}/verify` requires the admin key and a source from `config/approved_sources.json`. Verification is an administrator's documented provenance claim, not an automatic consequence of validation or `is_synthetic=false`. Verification records and revocations append one JSON object per line to `verification.json`; the uploaded CSV and original `metadata.json` remain unchanged. An optional evidence upload is stored separately by content hash.
- `POST /api/v1/data/datasets/{dataset_id}/revoke-verification` requires the admin key, appends the revocation reason and timestamp, and returns the derived unverified status.
- Deprecated `POST /api/v1/data/upload-csv` is an alias for `/assess-csv`.
- `MEDIPREDICT_ADMIN_API_KEY` configures the training-upload API key. Send it in `X-Admin-API-Key`; optionally identify the uploader with `X-Uploader`. Without the configured key, training upload is disabled.

Assessment results use `data_source="uploaded"` because the ingest path is an upload; source verification is not required for in-memory assessment or training upload. `is_synthetic` preserves the submitted declaration and remains `null` when it is omitted, blank, or mixed across records. Training-upload metadata uses the same ingest-path value and retains the supplied synthetic flag (or `null` when it is unknown or mixed).

Provenance status is derived and is never accepted from request data: `synthetic` for a dataset marked synthetic, `uploaded_unverified` for a non-synthetic file without a current valid verification record, and `verified` only when an authorized verification record matches the current stored-file SHA-256 and has not been revoked. A reporting period must cover the CSV's date range. If the stored-file hash changes, status falls back to `uploaded_unverified` and a warning is logged. The two-person check compares the stored uploader identity with the administrator identity supplied at verification; if either identity is unavailable, the response marks the verification `single_party`.

The approved-source registry ships with no approved sources. Its entries must be confirmed with the data owner (e.g., RMS / RBC / MoH) before use. The UI labels CSV intake as `Uploaded`; synthetic records remain labeled `Synthetic`. A `Verified Source` badge is shown only when an authorized verification record exists, and includes its source and verification details. Verification is optional for assessment and upload; the API's `uploaded_unverified` status identifies a stored dataset that has no verification record and does not prevent its normal upload or in-memory assessment.

## Label and split preparation

See [feature_design.md](./feature_design.md) for the versioned feature/label design, native-unit horizon, incomplete-window policy, and time-purged split rules. This contract describes source observations; it does not itself create labels or train a model.

## Persisted database provenance

The current Phase 2 migration adds nullable `is_synthetic` and `data_source` columns to `daily_stock_logs` and `predictions`. Existing rows are backfilled to `is_synthetic=true` and `data_source="synthetic"` as a conservative provenance designation. Uploaded CSV assessments and training uploads remain separate from those database tables.
