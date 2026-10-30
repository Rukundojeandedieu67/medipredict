# MediPredict Rwanda — Hospital Dashboard User Guide

This guide explains how to navigate the MediPredict Rwanda dashboard, interpret its screens, and understand what its controls do. It is written for hospital and health-supply staff evaluating the interface.

> **Deployment status:** This repository describes MediPredict as a demonstration and workflow prototype. This guide is not authorization to use it for hospital operations. The bundled inventory is synthetic, and the dashboard is not an approved source of truth. Before any operational pilot, the hospital and system owner must approve the deployment, verify the live data source and update process, and complete their privacy, security, clinical/operational, and supply-chain governance reviews.

## Important: demonstration dashboard

MediPredict is a demonstration and workflow prototype, not an operational source of truth.

- The bundled medicine stock, consumption, and risk data are synthetic. Some district indicators are unverified seed values.
- Risk tiers use rule-based days-of-cover calculations. A validated machine-learning model is not used for live classifications.
- Stock trajectories assume that reported consumption stays constant and that no deliveries arrive. They are simple scenarios, not forecasts.
- Transfer cards are suggestions, not approved transfer orders.
- Do not use the dashboard by itself to make clinical, procurement, allocation, or emergency-response decisions.

Confirm important findings with current physical stock counts, the responsible facility, and your organization's approved inventory and requisition processes.

## Before using the dashboard

### Accounts and access

You must sign in with an account issued by the workspace administrator. There is no public registration form.

| Account shown in the sidebar | What the interface allows |
|---|---|
| **Administrator** | Use the dashboard and create standard workspace-user accounts. New accounts are not administrators. |
| **Workspace user** | Use the dashboard and its available screens, including CSV assessment. |
| **Read-only demo** | View dashboard screens; the Upload Data screen is hidden and API write requests are rejected. Alert labels can still be changed locally in that browser, but they are not saved to the server. Do not use a shared demo account for hospital work. |

Use an individual account assigned to you. Sign out when finished on a shared workstation. The current UI does not provide password reset, account deactivation, or an audit-ready record of staff actions; ask the administrator to manage access.

The dashboard does not show facility-specific permissions: signed-in users can view the shared records loaded by the service. Do not treat signing in as proof that a user is authorized to see a particular facility's information. Confirm access requirements with the system owner before connecting hospital data.

### A safe review workflow

For any evaluation or approved pilot, use this sequence:

1. Sign in with your assigned account and read the demonstration/methodology notice.
2. Check the **Snapshot** reporting date, provenance labels, and any page-wide error banner. Confirm with the data owner that the snapshot is the intended source and is recent enough for the task.
3. Use **Refresh Data** and confirm the screen has no unresolved loading or data errors. **API Connected** only confirms a health endpoint responded; it does not prove that the database, source file, or displayed data is current.
4. Use Overview, Inventory, Stock Alerts, and Risk Register to find records that warrant verification. Search and filters only narrow the records already loaded; they do not update or correct source data.
5. Select **Inspect** and compare the facility, medicine code, units, reporting date, stock balance, consumption, and incoming deliveries against the facility ledger and approved source.
6. Document assignment, acknowledgement, decisions, and approvals in the hospital's approved shared system. The dashboard's alert status is browser-local and is not an operational handoff.
7. Treat transfer suggestions and recommended actions as prompts for a qualified human review. Obtain all required approvals before changing orders or moving stock.
8. Sign out. Do not leave an authenticated session open on a shared device.

If the source, freshness, unit, or provenance cannot be confirmed, stop and refer the record to the responsible data owner rather than acting on the dashboard.

## Getting oriented

### Navigation

Use the sidebar to move between **Overview**, **Inventory**, **Stock Alerts**, **Risk Register**, **Stock Transfers**, **Model Insights**, and **Upload Data**. On a smaller screen, open the navigation using the menu button in the header.

### Connection, snapshot, and refresh

- The sidebar status card shows whether the dashboard can reach its service. **API Connected** only means the health check succeeded; it does not confirm that the displayed data is current or verified. The API health check is separate from requests for inventory, alerts, transfers, and metrics.
- The top bar's **Snapshot** date is the latest reporting date in the loaded dashboard data. It is not necessarily today's date.
- Select **Refresh Data** to reload the summary, risk register, alerts, transfer suggestions, and model-insight information from the backend. Filters and page selections are separate from this refresh.
- If an error banner appears, read it and use **Retry** or **Refresh Data**. Some data sections can fail while others load. If the problem continues, contact the dashboard administrator. Do not rely on figures left on screen after an error.

The dashboard also displays a demonstration and methodology notice. Read it before interpreting results.

## Overview

Start here for a high-level view of the loaded snapshot:

- **Monitored Facilities**, **Open / Unresolved Alerts**, **Medicines Tracked**, and **Rebalancing Transfers** summarize the records currently shown.
- Select a summary card to open its related page.
- **Medicines Requiring Attention First** highlights stock-outs and records with critical cover. Use **Inspect** to open the record details, or **View All Alerts** to review warnings.
- **Stock Coverage Distribution** summarizes the risk tiers in the displayed dataset. It is a distribution of available records, not a measure of system-wide medicine availability.
- Other overview panels may summarize provincial records or recent alerts/transfers. Treat their rankings and counts as leads to investigate, not confirmed operational findings.

When there are no priority records, do not assume that stock is adequate: check the reporting date, provenance labels, and whether the underlying data is complete.

The facility and medicine counts are distinct values in the loaded records. Total stock is a sum of reported units and may combine different products or pack sizes; do not treat it as a directly comparable total across medicines.

## Inventory

Use **Inventory** to search and inspect facility-medicine records.

1. Type a medicine name/code, facility, or district in the search box.
2. Narrow results with **District**, **Risk Level**, **Status**, and **Data Origin** filters.
3. Select a table heading to sort by medicine, facility, stock, daily consumption, cover, or risk.
4. Use the page controls to move between records or change how many rows are shown.
5. Select **Inspect** to open a detailed medicine view.
6. Select **Reset** to clear active filters.

The table includes reported stock, daily use, days of cover, a short stock trajectory, risk tier, and provenance/method badges. It starts sorted by cover (lowest first), with 25 records per page. A dash or unavailable cover means there is not a usable cover estimate; it does not indicate that stock is safe. The **Uploaded CSV** data-origin filter identifies uploaded records; the **Non-synthetic data only** filter does not, by itself, mean a source has been verified.

## Stock Alerts

Use **Stock Alerts** to investigate warnings from the latest available records.

- Search by facility, district, medicine, or the alert reason.
- Filter by **Severity**, **Alert Type**, or **Status**. The summary cards at the top can also filter critical alerts, warnings, or items marked resolved.
- Read the alert's reason, reporting date, stock balance, daily consumption, estimated cover, and depletion scenario.
- Select the status badge to cycle from **Open / Action Required** to **Acknowledged**, then **Resolved**, then back to **Open**.
- Select **Check Transfers** to view transfer suggestions, when available, or **Full Audit** to inspect the matching inventory record.
- Use **Reset** or **Reset Filters** to remove filters.

The alert status is a convenience for the current browser, not a shared assignment or audit trail. It is saved in browser local storage on that device/profile, not on the user's account or server. It is not synchronized to other devices and can be visible to another person using the same browser profile. Clearing browser storage can remove it. Record follow-up in your organization's approved shared workflow.

The recommended action shown on a card is a prompt for investigation, not an instruction or authorization. Verify the record and physical stock before acting. In-app alerts do not mean that an email or text notification has been sent. Changing an alert to **Acknowledged** or **Resolved** does not notify colleagues or change the underlying inventory.

## Risk Register

Use **Risk Register** for a paginated, searchable view of risk-classified records.

1. Search for a facility, district, medicine, or medicine code.
2. Select a district and risk tier to narrow the results.
3. Review stock, daily consumption, the 14-day scenario, cover, risk tier, and the method/provenance badges.
4. Select **Inspect** for more detail.
5. Change the page size or use the page controls to browse matching records.

The displayed method is rule-based. A confidence value or historical metric elsewhere in the dashboard should not be read as proof of real-world predictive performance.

## Stock Transfers

Use **Stock Transfers** to explore possible donor-recipient matches:

- Search by medicine or either facility.
- Filter by district. A district match may refer to either the donor or the recipient.
- Each card shows the medicine, suggested quantity, donor and recipient, districts, provenance, and their reported cover. Current candidate rules identify donors with more than 30 days of cover and recipients with less than 14 days; the proposed amount aims to leave at least 30 days with the donor and restore at least 14 days at the recipient.

The page describes a proposed minimum donor buffer and target recipient cover. Before considering a movement, confirm stock counts, demand, batch and expiry, cold-chain needs, transportation, donor safety stock, and required approvals. The dashboard does not initiate or authorize a transfer.

## Model Insights

Use **Model Insights** to read the dashboard's methodology and governance disclosures. The page may show a development metric or feature-importance information when such metadata is available.

The page explicitly notes that live classifications use rule-based fallback logic and that predictive ML serving is not enabled. Any development metrics or signals shown are not evidence of clinical or operational performance. Do not interpret a blank metric as zero or a missing model as a successful model.

## What the UI does not do

- It does not record a physical stock count, edit the shared snapshot, place an order, dispatch stock, or approve a transfer.
- It does not assign alerts to a staff member or maintain a shared acknowledgement/resolution history.
- It does not guarantee that an alert email or SMS was sent. Notification dispatch is not a control in the dashboard.
- It does not turn an uploaded assessment into dashboard inventory or a production model.
- It does not provide facility-level access restrictions or an audit trail suitable for hospital governance.

Use the hospital's authorized inventory, procurement, communications, and incident-management systems for those tasks.

## Upload Data: assess a CSV

The **Upload & Assess** tab submits a facility-inventory CSV to the assessment endpoint. A successful assessment file is retained in configured storage, and the page displays the assessment result. This does **not** replace or update the shared dashboard snapshot, update the inventory records displayed elsewhere, or train/promote a model. Results belong to the current page view; use your approved records system if you need to preserve the review.

The upload page also has a **Registered Uploads** panel. This is a separate, administrator-key-protected dataset registry view; it is not a list of every CSV assessed in the page above. Only use it if your administrator has explicitly authorized you and provided the key. Never enter an administrator key on a shared or untrusted computer.

### Required CSV headers

The first row must contain these exact column names:

| Header | What to provide |
|---|---|
| `facility_id` | A stable, non-empty facility identifier |
| `item_id` | A stable, non-empty medicine or product identifier |
| `date` | Reporting date written as `YYYY-MM-DD` |
| `stock_on_hand` | Available stock in the item's stock unit; zero or greater |
| `units_consumed` | Quantity consumed for the reporting period; zero or greater |
| `units_received` | Quantity received for the reporting period; zero or greater |

Example:

```csv
facility_id,item_id,date,stock_on_hand,units_consumed,units_received,is_synthetic
RW-KAY-HC01,AL-20120,2026-03-01,150,25,0,false
RW-GAS-DH02,PARACET-500,2026-03-01,0,40,0,false
```

The **CSV Specifications** tab in the dashboard also lists the required and common optional columns and provides a sample. The more complete validation and training contract is documented in [the data contract](./data_contract.md).

Common optional columns shown in the UI are `is_synthetic`, `stockout_flag`, `lead_time_days`, `reorder_level`, `facility_type`, and `region`. The backend contract describes additional optional fields. `is_synthetic=false` or an omitted synthetic flag does not establish that a source is verified.

### Before submitting

- Use consistent item-specific units for stock, consumption, and receipts.
- Ensure dates and numbers are valid; stock, consumption, and receipts must not be negative. Keep all quantities in the same documented, item-specific unit.
- Avoid duplicate facility-item reporting periods and keep each facility-item history chronological.
- Include `is_synthetic=true` when records are generated or simulated. If synthetic status is omitted, it remains unknown; an upload is not automatically real or verified.
- Do not include patient identifiers or patient-level information.
- The interface accepts CSV files up to 20 MB. The current assessment supports daily-frequency data only. Although the file-selection help text mentions monthly files, a monthly file cannot currently be assessed as a day-based estimate and the backend rejects it.

### Select and assess

1. Open **Upload Data** and stay on **Upload & Assess**.
2. Choose a `.csv` file in the drop area.
3. Review the required-column check and the small sample preview. The preview reads only the beginning of the file and splits text on commas for display; it is only a quick check and does not replace full CSV parsing or server validation.
4. If the interface reports a missing header or a file-size/type problem, correct it and choose the file again.
5. Select **Run In-Memory Risk Assessment**.
6. Review the assessment summary, validation errors and warnings, risk tiers, and the displayed sample of assessed records. Correct data problems before relying on any result.

If the assessment fails, read the message shown on the page. Common causes include missing headers, malformed dates or values, negative numbers, duplicate records, or a monthly file. Ask the administrator for help if the issue appears to be with dashboard availability rather than the CSV.

The results show rule-based calculations, not a learned forecast. Cover is `stock_on_hand / units_consumed` when consumption is positive. The 7- and 14-day scenarios subtract consumption at a constant rate and assume no incoming deliveries; `units_received` does not alter those projections. Zero consumption means cover is unavailable. Only a limited sample of assessed rows and validation messages is displayed. A successful CSV is retained in configured storage; do not upload patient-identifiable, confidential, or otherwise sensitive information.

### Provenance badges

- **Synthetic** identifies demonstration/synthetic data.
- **Uploaded** identifies data supplied through a CSV; it does not confirm its source.
- **Verified Source** indicates that a source verification record is displayed. It is not a guarantee that every value is correct or suitable for a decision.
- **Rule-based estimate** identifies the days-of-cover method rather than a trained-model prediction.

### Registered Uploads

The bottom of the **Upload & Assess** page has a **Registered Uploads** panel. This is separate from selecting a CSV for assessment and lists datasets registered through the restricted dataset workflow. It is intended for authorized users who have been given an administrator key:

1. Enter the key in the password field.
2. Select **Load registered uploads**.
3. Review each dataset's displayed provenance status, row count, date period, uploader, verification details, and any warning.

If you are not an authorized administrator, leave this panel unused and ask the system administrator for help. Do not share the key or enter it on a shared/untrusted computer. Loading this list does not make an uploaded file verified.

## Reading the main labels

| Display | Interpretation |
|---|---|
| **Critical** | Zero stock, a recorded stock-out, or fewer than 7 days of calculated cover. Verify urgently with the source. |
| **Moderate** | 7 through 14 days of calculated cover. Confirm the latest stock and replenishment plan. |
| **Stable** | More than 14 days of calculated cover. It is not a guarantee of availability or data quality. |
| **Unknown / Cover Unavailable** | The interface cannot calculate a meaningful cover value, often because consumption is zero, missing, or invalid. Investigate the source data. |
| **Snapshot** | Reporting date associated with the current displayed dataset, not necessarily today's date. |

For positive daily consumption, cover is calculated as `stock on hand / daily consumption`. The 7- and 14-day scenarios subtract consumption at the same rate and assume no incoming deliveries. They do not model changing demand, replenishment uncertainty, expiry, or stock quality.

## Good practices for users

1. Check the snapshot date and provenance before interpreting any count or badge.
2. Verify concerning records with the facility and authoritative source; report discrepancies to the data owner.
3. Treat the dashboard's recommendations as prompts for human review, never as automatic orders or transfers.
4. Use approved organizational systems for task ownership, decisions, approvals, and audit history.
5. Protect uploaded files and administrator credentials; do not upload patient-level or other sensitive information.
6. If information appears stale, incomplete, or contradictory, stop and ask the data owner or administrator rather than relying on the dashboard.

## Troubleshooting

| What you see | What to do |
|---|---|
| Sign-in page or session no longer works | Sign in again. If access is still denied, ask the workspace administrator to confirm your account. |
| **API Offline** or a page-wide service error | Use **Retry** or **Refresh Data** once. If it persists, contact the system administrator; do not act on figures left on screen. |
| API says connected, but one section has an error or no data | Treat that section as unavailable. A successful health check does not validate its data request, source file, or storage. Ask the administrator to check service logs and the configured data source. |
| CSV is rejected | Check the required header spelling, `.csv` format, 20 MB limit, date format, non-negative quantities, duplicate facility-item dates, and daily-frequency requirement. Read the validation message and correct the source file before retrying. |
| Registered Uploads reports access denied or unavailable | Do not keep retrying or share an administrator key. Ask an authorized administrator to check the key, account, database, and storage configuration. |
| An alert or transfer suggestion does not match the facility ledger | Stop and verify the source record, units, snapshot date, physical balance, consumption, and deliveries with the responsible data owner. The dashboard does not resolve source discrepancies. |

## Related documentation

- [Inventory observation CSV contract](./data_contract.md) — field definitions, validation rules, frequency, and endpoint behavior.
- [Dataset provenance](../ml_engine/datasets/PROVENANCE.md) — repository dataset origin and provenance notes.
- [Deployment plan](./deployment_plan.md) — deployment considerations and operational readiness checks.
