# MediPredict Rwanda — Dashboard User Guide

This guide covers what an end user can see and do in the MediPredict Rwanda web dashboard. It is intentionally focused on the frontend: navigation, page controls, displays, CSV assessment, and how to interpret the information shown.

## Important: demonstration dashboard

MediPredict is a demonstration and workflow prototype, not an operational source of truth.

- The bundled medicine stock, consumption, and risk data are synthetic. Some district indicators are unverified seed values.
- Risk tiers use rule-based days-of-cover calculations. A validated machine-learning model is not used for live classifications.
- Stock trajectories assume that reported consumption stays constant and that no deliveries arrive. They are simple scenarios, not forecasts.
- Transfer cards are suggestions, not approved transfer orders.
- Do not use the dashboard by itself to make clinical, procurement, allocation, or emergency-response decisions.

Confirm important findings with current physical stock counts, the responsible facility, and your organization's approved inventory and requisition processes.

## Getting oriented

### Navigation

Use the sidebar to move between **Overview**, **Inventory**, **Stock Alerts**, **Risk Register**, **Stock Transfers**, **Model Insights**, and **Upload Data**. On a smaller screen, open the navigation using the menu button in the header.

### Connection, snapshot, and refresh

- The sidebar status card shows whether the dashboard can reach its service. **API Connected** only means the health check succeeded; it does not confirm that the displayed data is current or verified.
- The top bar's **Snapshot** date is the latest reporting date in the loaded dashboard data. It is not necessarily today's date.
- Select **Refresh Data** to reload the displayed summary, inventory, alerts, transfer suggestions, and model-insight information.
- If an error banner appears, read it and use **Retry** or **Refresh Data**. If the problem continues, contact the dashboard administrator. Do not rely on old figures remaining on screen.

The dashboard also displays a demonstration and methodology notice. Read it before interpreting results.

## Overview

Start here for a high-level view of the loaded snapshot:

- **Monitored Facilities**, **Open / Unresolved Alerts**, **Medicines Tracked**, and **Rebalancing Transfers** summarize the records currently shown.
- Select a summary card to open its related page.
- **Medicines Requiring Attention First** highlights stock-outs and records with critical cover. Use **Inspect** to open the record details, or **View All Alerts** to review warnings.
- **Stock Coverage Distribution** summarizes the risk tiers in the displayed dataset. It is a distribution of available records, not a measure of system-wide medicine availability.
- Other overview panels may summarize provincial records or recent alerts/transfers. Treat their rankings and counts as leads to investigate, not confirmed operational findings.

When there are no priority records, do not assume that stock is adequate: check the reporting date, provenance labels, and whether the underlying data is complete.

## Inventory

Use **Inventory** to search and inspect facility-medicine records.

1. Type a medicine name/code, facility, or district in the search box.
2. Narrow results with **District**, **Risk Level**, **Status**, and **Data Origin** filters.
3. Select a table heading to sort by medicine, facility, stock, daily consumption, cover, or risk.
4. Use the page controls to move between records or change how many rows are shown.
5. Select **Inspect** to open a detailed medicine view.
6. Select **Reset** to clear active filters.

The table includes reported stock, daily use, days of cover, a short stock trajectory, risk tier, and provenance/method badges. A dash or unavailable cover means there is not a usable cover estimate; it does not indicate that stock is safe.

## Stock Alerts

Use **Stock Alerts** to investigate warnings from the latest available records.

- Search by facility, district, medicine, or the alert reason.
- Filter by **Severity**, **Alert Type**, or **Status**. The summary cards at the top can also filter critical alerts, warnings, or items marked resolved.
- Read the alert's reason, reporting date, stock balance, daily consumption, estimated cover, and depletion scenario.
- Select the status badge to cycle from **Open / Action Required** to **Acknowledged**, then **Resolved**, then back to **Open**.
- Select **Check Transfers** to view transfer suggestions, when available, or **Full Audit** to inspect the matching inventory record.
- Use **Reset** or **Reset Filters** to remove filters.

The alert status is a convenience for the current browser, not a shared assignment or audit trail. It is saved in browser storage and may not be visible to another user or device. Record follow-up in your organization's approved shared workflow.

The recommended action shown on a card is a prompt for investigation, not an instruction or authorization. Verify the record and physical stock before acting. In-app alerts do not mean that an email or text notification has been sent.

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
- Each card shows the medicine, suggested quantity, donor and recipient, districts, and their reported cover.

The page describes a proposed minimum donor buffer and target recipient cover. Before considering a movement, confirm stock counts, demand, batch and expiry, cold-chain needs, transportation, donor safety stock, and required approvals. The dashboard does not initiate or authorize a transfer.

## Model Insights

Use **Model Insights** to read the dashboard's methodology and governance disclosures. The page may show a development metric or feature-importance information when such metadata is available.

The page explicitly notes that live classifications use rule-based fallback logic and that predictive ML serving is not enabled. Any development metrics or signals shown are not evidence of clinical or operational performance. Do not interpret a blank metric as zero or a missing model as a successful model.

## Upload Data: assess a CSV

The **Upload & Assess** tab is for checking and viewing an assessment of a selected facility-inventory CSV. It does not replace the shared dashboard snapshot. The user interface does not provide an approval or promotion workflow for the assessment.

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

The **CSV Specifications** tab in the dashboard also lists required and optional columns and provides a sample.

### Before submitting

- Use consistent item-specific units for stock, consumption, and receipts.
- Ensure dates and numbers are valid; stock, consumption, and receipts must not be negative.
- Avoid duplicate facility-item reporting periods and keep each facility-item history chronological.
- Include `is_synthetic=true` when records are generated or simulated. If synthetic status is omitted, it remains unknown; an upload is not automatically real or verified.
- Do not include patient identifiers or patient-level information.
- The interface accepts CSV files up to 20 MB. The current assessment supports daily-frequency data only; monthly data cannot be assessed as a day-based estimate.

### Select and assess

1. Open **Upload Data** and stay on **Upload & Assess**.
2. Choose a `.csv` file in the drop area.
3. Review the required-column check and the small sample preview. The preview is only a quick check and does not replace full validation.
4. If the interface reports a missing header or a file-size/type problem, correct it and choose the file again.
5. Select **Run In-Memory Risk Assessment**.
6. Review the assessment summary, validation errors and warnings, risk tiers, and the displayed sample of assessed records. Correct data problems before relying on any result.

If the assessment fails, read the message shown on the page. Common causes include missing headers, malformed dates or values, negative numbers, duplicate records, or a monthly file. Ask the administrator for help if the issue appears to be with dashboard availability rather than the CSV.

The results show rule-based calculations, not a learned forecast. Only a limited sample of assessed rows and validation messages is displayed. Accepted assessment files may be retained by the system; do not upload sensitive information.

### Provenance badges

- **Synthetic** identifies demonstration/synthetic data.
- **Uploaded** identifies data supplied through a CSV; it does not confirm its source.
- **Verified Source** indicates that a source verification record is displayed. It is not a guarantee that every value is correct or suitable for a decision.
- **Rule-based estimate** identifies the days-of-cover method rather than a trained-model prediction.

### Registered Uploads

The bottom of the **Upload & Assess** page has a **Registered Uploads** panel. This is separate from selecting a CSV for assessment. It is intended for authorized users who have been given an administrator key:

1. Enter the key in the password field.
2. Select **Load registered uploads**.
3. Review each dataset's displayed provenance status, row count, date period, uploader, verification details, and any warning.

If you are not an authorized administrator, leave this panel unused and ask the system administrator for help. Do not share the key or enter it on a shared/untrusted computer. Loading this list does not make an uploaded file verified.

## Reading the main labels

| Display | Interpretation |
|---|---|
| **Critical** | Usually zero stock/recorded stock-out or fewer than 7 days of calculated cover. Verify urgently with the source. |
| **Moderate** | Usually 7–14 days of calculated cover. Confirm the latest stock and replenishment plan. |
| **Stable** | Usually more than 14 days of calculated cover. It is not a guarantee of availability or data quality. |
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
