# MediPredict Rwanda — End-User Guide

This guide is for supply-chain officers, facility data staff, and reviewers exploring the MediPredict Rwanda dashboard. It explains how to navigate the prototype, prepare a CSV for assessment, interpret results, and use the system responsibly.

## 1. Before you begin

MediPredict is currently a **demonstration and workflow prototype**, not an operational source of truth:

- The bundled inventory, consumption, and risk records are synthetic demonstration data. Some district indicators are unverified seed values.
- Live risk classifications use rule-based days-of-cover logic. A validated machine-learning model is not enabled for live serving.
- Stock projections assume the reported consumption rate continues unchanged and no new stock arrives. They are scenarios, not calibrated forecasts.
- Transfer matches are suggestions calculated from reported balances, not approved movements.
- Do not use this system alone to make clinical, procurement, allocation, or emergency-response decisions.

Confirm all important findings with current physical stock counts, the responsible facility, and the authoritative inventory/requisition system.

## 2. Open the dashboard

When the system is running, open the dashboard URL provided by your administrator. In a local Docker Compose setup, it is <http://localhost:8080>.

The left navigation opens each workspace. The status card at the bottom of the navigation reports whether the API health check passed. The top bar shows the latest reporting date in the currently loaded dashboard dataset and provides **Refresh Data**.

If the API is offline, check with the system administrator rather than relying on any figures still visible in the page. A successful health check means only that the API responded; it does not prove that the underlying data is complete, current, or verified.

## 3. A practical review workflow

1. **Check the data before interpreting it.** Note the snapshot date. Look for the data-status/provenance labels (such as **Synthetic**, **Uploaded**, or **Verified Source**) and read the demonstration and methodology notice.
2. **Start at Overview.** Use the summary and priority list to find records that may need investigation. Treat the counts as counts in the loaded dataset, not confirmed facility-wide totals.
3. **Investigate in Inventory or Risk Register.** Search by medicine name/code, facility, or district. Filter and sort to narrow the list. Open a row to inspect its details, reported stock, consumption, cover, and data-status labels.
4. **Review Stock Alerts.** Search or filter by severity, alert type, and status. Follow up with the facility/source owner to verify the report. Acknowledge an alert when someone has begun reviewing it; mark it resolved only after confirming the underlying issue is addressed.
5. **Use Stock Transfers as a discussion prompt.** Confirm current stock, demand, expiry, cold-chain requirements, transport, approvals, and donor safety stock before proposing or authorizing any movement. A displayed match is not a transfer order.
6. **Record the decision outside the prototype.** Use the organization’s approved inventory, requisition, incident, and audit processes for assignments, approvals, and follow-up.
7. **Refresh after the source data changes.** Confirm that the reporting date has advanced as expected and verify the underlying source update with the data owner.

### What the risk labels mean

For records with usable positive consumption, the rule-based calculation is:

`estimated days of cover = reported stock on hand / average daily consumption`

The normal thresholds are **Critical** below 7 days, **Moderate** from 7 through 14 days, and **Stable** above 14 days. Reported zero stock or a recorded stock-out is critical. If consumption is missing, invalid, or zero, cover may be unavailable or classified as unknown; do not interpret a missing estimate or a “Stable” display from a special assessment case as evidence of adequate supply.

Seven- and fourteen-day stock trajectories subtract average daily consumption from current stock and do not include expected deliveries. These values do not model changing demand, replenishment uncertainty, expiry, stock quality, or other operational constraints.

### Alert statuses are browser-local

The **Open**, **Acknowledged**, and **Resolved** labels are saved in local storage in the browser you are using. They are not shared with other users, synchronized to a central service, or a formal audit record. Clearing browser data or switching browsers may remove or change the locally tracked statuses. Use your organization’s approved system for shared ownership and audit history.

In-app alerts are not the same as email/SMS delivery. The dashboard does not send notifications merely because it is open; any configured notification dispatch is an administrator-controlled operation.

## 4. Assess an inventory CSV

The **Upload Data** page’s **Upload & Assess** tab assesses the selected file. It does not replace the dashboard’s shared snapshot or enroll the file as an approved training dataset. Accepted assessment files are retained in the configured storage backend; ask your administrator how long that storage is retained and who can access it.

### Required columns

The CSV must have a header row and these exact column names:

| Column | Meaning |
|---|---|
| `facility_id` | Stable, non-empty facility identifier |
| `item_id` | Stable, non-empty medicine/item identifier |
| `date` | Reporting date in `YYYY-MM-DD` format |
| `stock_on_hand` | Available stock units at the reported date; zero or greater |
| `units_consumed` | Units consumed during the reporting period; zero or greater |
| `units_received` | Units received during the reporting period; zero or greater |

Example:

```csv
facility_id,item_id,date,stock_on_hand,units_consumed,units_received,is_synthetic
RW-KAY-HC01,AL-20120,2026-03-01,150,25,0,false
RW-GAS-DH02,PARACET-500,2026-03-01,0,40,0,false
```

### Recommended optional columns

Include `is_synthetic` and set it to `true` for generated or simulated records. If it is omitted or blank, synthetic status is **unknown**; the system does not assume the data is real. Other supported optional columns include:

- `stockout_flag` (`true`/`false`) and `stock_out_days`
- `lead_time_days` and `reorder_level`
- `facility_type`, `region`, and `district`
- `urban_rural`, `item_category`, and `reporting_completeness`
- `catchment_population`, `rainfall_anomaly`, and `temperature_anomaly`
- `program_funded`, `cold_chain`, and `outbreak_flag`
- `district_replenishment_date` in `YYYY-MM-DD` format

See the full [Inventory observation CSV contract](data_contract.md) for types, units, validation rules, and all optional fields.

### Prepare and submit

1. Export a CSV containing facility-item observations only; do not include patient identifiers or patient-level data.
2. Use one stable identifier per facility and item. Use consistent item-specific units for stock, consumption, receipts, and reorder levels.
3. Ensure dates are valid ISO dates, values are finite and non-negative, and each facility-item-period appears only once.
4. Keep each facility-item history in chronological order. Missing periods and unusual consumption/stock ratios may be reported as warnings.
5. On **Upload Data**, choose the CSV and inspect the column check and sample preview.
6. Select **Run In-Memory Risk Assessment**. Review the validation report and warnings before interpreting the displayed assessment.

Assessment uploads are limited to 20 MB. The current rule-based risk assessment supports **daily-frequency data only**. Monthly files may be validated/prepared through the data workflow but are not given a misleading day-based assessment; the assessment endpoint returns an error for monthly data. The configured API frequency must match the frequency of the file.

The results page shows an assessment summary and a limited sample of records. A successful validation does not mean that source data is accurate or independently verified. An assessment is rule-based, not a trained-model prediction.

### Understand provenance labels

| Label | Meaning |
|---|---|
| **Synthetic** | The data is marked or derived as synthetic demonstration data. It is not evidence of real facility conditions. |
| **Uploaded** | The data was supplied through an upload; the source has not necessarily been independently checked. |
| **Verified Source** | An administrator has recorded a provenance verification against an approved source. This checks documented origin, not every value’s accuracy or fitness for a particular decision. |

Uploading a file does not make it verified. Do not set `is_synthetic=false` unless the source owner can support that assertion, and do not treat it alone as verification.

## 5. Registered datasets and administrator-only intake

The **Registered Uploads** area on the Upload Data page is for viewing registered dataset provenance and requires an administrator API key. Keep that key private; do not paste it into shared machines or browser screenshots.

The protected `POST /api/v1/data/training-upload` endpoint is different from the normal **Upload & Assess** flow: it registers a validated dataset and queues a candidate-training job. Access requires an administrator key and database-backed features. A queued job is not a deployed model. Candidate models are not automatically promoted or served, and synthetic or unverified data cannot qualify as an approved live model.

Only authorized data stewards should use this intake. First confirm data-owner approval, provenance, frequency, schema, retention/access controls, and the required minimum history. Check training status and provenance through the protected API before drawing conclusions. See the [Data contract](data_contract.md), [API documentation](../backend/README.md), and [ML pipeline notes](../ml_engine/README.md).

## 6. Recommendations for organizations evaluating MediPredict

These are recommended adoption steps, not system-generated assurances:

1. **Start with a data-governance review.** Assign owners for each source, reporting period, facility/item identifier, unit of measure, provenance claim, and correction process.
2. **Pilot in shadow mode.** Compare dashboard records with independently checked facility counts and existing supply-chain procedures. Log discrepancies and false alarms; do not let the prototype trigger orders or transfers.
3. **Set operational definitions with stakeholders.** Agree on reporting cadence, stock-out evidence, consumption periods, stock units, alert thresholds, escalation routes, and acceptable data freshness before using results in routine reviews.
4. **Validate the full data pipeline.** Measure completeness, duplicate rates, missing periods, late reports, unit consistency, and district/facility mapping. Investigate validation warnings rather than silently accepting them.
5. **Protect sensitive data.** Keep uploads to the minimum facility-item information needed. Define authorized users, storage location, retention/deletion, backups, audit expectations, and incident response. Do not send real or sensitive data to third-party services without explicit owner approval.
6. **Keep human approval explicit.** Require staff to confirm stock, receipts, expiry, and transport conditions and to follow existing requisition/transfer authorization.
7. **Require evidence before model use.** Before enabling any ML model, require verified real-world data, leakage-safe temporal evaluation, performance checks relevant to decisions and subgroups, independent review, reproducible artifact hashes, monitoring, rollback, and a documented owner sign-off. Development metrics or synthetic tests are not deployment evidence.
8. **Operationalize only after a controlled pilot.** Establish named owners, shared alert/decision tracking, support and escalation, uptime/backups, and routine data-quality reviews. The current browser-local alert statuses are not suitable as a shared operational record.

## 7. Troubleshooting

| Symptom | What to check |
|---|---|
| **API Offline** or page cannot load data | Confirm the API container/service is running; check `http://localhost:8000/api/v1/health` in a local Compose setup; ask the administrator to inspect API logs. |
| API is connected but dashboard data is unavailable | Ask the administrator to check the configured CSV/object-storage location and its schema. A healthy API does not guarantee its data source is available. |
| CSV is rejected before upload | Confirm the `.csv` extension, size under 20 MB, all required headers, and no typos in column names. |
| CSV fails validation | Read the row/column-specific errors. Correct invalid dates/numbers, negative values, duplicate facility-item-periods, and malformed booleans. Review warnings for missing periods or unusual values. |
| Monthly CSV cannot be assessed | This is expected: the current rule-based assessment accepts daily-frequency data only. Do not convert monthly consumption to daily values without a documented, reviewed method. |
| Assessment says cover is unavailable | Check that consumption is present and greater than zero and that stock/consumption use compatible units. Confirm the original record with its source. |
| Dataset registry does not load | The registry needs database-backed features and a valid administrator API key. Contact the system administrator; do not share the key in chat or email. |
| Numbers do not match a facility report | Compare the reporting date, item identifier, units, stock balance, consumption period, and source extract. Correct the source or report the discrepancy; do not treat the dashboard as the authority. |

## 8. Further documentation

- [Project README and quick start](../README.md)
- [Inventory observation CSV contract](data_contract.md)
- [Stock warnings and notifications](alerts.md)
- [Dataset and field provenance](../ml_engine/datasets/PROVENANCE.md)
- [Deployment plan](deployment_plan.md)
- [Backend/API setup](../backend/README.md)
- [ML pipeline notes](../ml_engine/README.md)
