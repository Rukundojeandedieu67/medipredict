# Stock warnings and notifications

## In-app warnings

The `Stock alerts` page reports current snapshot warnings for the latest available row per facility and medicine:

- **Stock-out / Critical:** reported stock is zero, or estimated stock cover is below 7 days.
- **Low stock / Warning:** estimated stock cover is from 7 through 14 days.
- **Cover unavailable / Warning:** consumption is zero or unavailable, so cover cannot be calculated. The risk register labels this case `UNKNOWN`, not `STABLE`.
- Above 14 days is classified as `STABLE` and is not listed as an active alert.

Cover is `stock_units / daily_consumption`. The risk register and alert API also expose estimated remaining stock after 7 and 14 days, calculated as `max(0, current stock - average daily consumption × days)`. These projections assume the reported consumption rate remains constant and no incoming receipts arrive; if consumption is zero, negative, or invalid the projection is unavailable (except stock already at zero, which remains zero). They are transparent arithmetic scenarios, not calibrated forecasts or evidence of real-world performance. Verify stock, consumption, and expected deliveries before acting. In-app entries retain their provenance labels; synthetic alerts are explicitly marked Synthetic.

Risk classification uses reported available stock: zero stock or a recorded stock-out is Critical regardless of consumption; otherwise fewer than 7 days of cover is Critical, 7-14 days is Moderate, over 14 days is Stable, and cover is Unknown when consumption cannot be estimated. The API does not serve a learned model in this phase.

`GET /api/v1/alerts` returns the current active alert list. It does not send notifications.

## Email and SMS

`POST /api/v1/alerts/dispatch` sends a digest through configured SMTP and/or Twilio SMS. It requires `X-Admin-API-Key` matching `MEDIPREDICT_ADMIN_API_KEY`. Call it from an authorized scheduler after refreshing the source data; dashboard reads do not trigger outbound messages.

Set recipients and provider credentials with environment variables. Do not commit credentials or place them in client-side code.

| Environment setting | Purpose |
|---|---|
| `MEDIPREDICT_ALERT_SMTP_HOST`, `MEDIPREDICT_ALERT_SMTP_PORT` | SMTP server; port defaults to 587 |
| `MEDIPREDICT_ALERT_SMTP_STARTTLS` | Enable STARTTLS; defaults to true |
| `MEDIPREDICT_ALERT_SMTP_USERNAME`, `MEDIPREDICT_ALERT_SMTP_PASSWORD` | Optional SMTP authentication; configure both or neither |
| `MEDIPREDICT_ALERT_EMAIL_FROM`, `MEDIPREDICT_ALERT_EMAIL_TO` | Sender and comma-separated authorized recipients |
| `MEDIPREDICT_ALERT_TWILIO_ACCOUNT_SID`, `MEDIPREDICT_ALERT_TWILIO_AUTH_TOKEN` | Twilio credentials |
| `MEDIPREDICT_ALERT_TWILIO_FROM`, `MEDIPREDICT_ALERT_SMS_TO` | Twilio sender and comma-separated recipient numbers |
| `MEDIPREDICT_ALERT_COOLDOWN_HOURS` | Repeat-notification interval; defaults to 24 hours |

Outbound notifications are **suppressed** unless every latest inventory row is explicitly `is_synthetic=false` and has `data_source="real"`. Uploaded and synthetic data can appear in the in-app alert list but cannot trigger emails or texts. An alert sends on first detection, severity escalation, recovery, or after the configured cooldown. Notification state is stored in `alert_notification_states`; migration `0003_alert_notification_state` creates this table and is reversible.

Email/SMS is not enabled until provider settings and recipient lists are deliberately configured. Delivery failure is reported by the endpoint; no credential values are returned in the response.
