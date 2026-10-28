from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import math
import smtplib
from typing import Any

import requests
from sqlalchemy.orm import Session

from .config import Settings, settings
from .models import AlertNotificationState
from .ml_service import estimate_stock_after_days
from .schemas.api import StockAlert


_SEVERITY_RANK = {"warning": 1, "critical": 2}


def _alert_id(facility: str, medicine_code: str, district: str = "") -> str:
    key = (
        f"{facility.strip().casefold()}\0{district.strip().casefold()}"
        f"\0{medicine_code.strip().casefold()}"
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build_stock_alerts(rows: list[dict[str, Any]]) -> list[StockAlert]:
    alerts: list[StockAlert] = []
    for row in rows:
        try:
            stock = float(row["stock_units"])
        except (TypeError, ValueError):
            stock = math.nan
        try:
            consumption = float(row["daily_consumption"])
        except (TypeError, ValueError):
            consumption = math.nan
        cover_value = row.get("lead_time_days")
        try:
            cover = float(cover_value) if cover_value is not None else None
        except (TypeError, ValueError):
            cover = None
        facility = str(row["facility"])
        medicine_code = str(row["medicine_code"])
        stockout_flag = row.get("stockout_flag")
        recorded_stockout = stockout_flag is True or (
            isinstance(stockout_flag, str) and stockout_flag.strip().casefold() == "true"
        )
        try:
            stock_out_days = float(row.get("stock_out_days", 0) or 0)
        except (TypeError, ValueError):
            stock_out_days = math.nan
        recorded_stockout = recorded_stockout or (
            math.isfinite(stock_out_days) and stock_out_days > 0
        )
        if recorded_stockout or (math.isfinite(stock) and stock == 0):
            alert_type = "stockout"
            severity = "critical"
            risk_level = "CRITICAL"
            message = "Reported stock is zero. Confirm physical stock and arrange urgent replenishment."
        elif (
            (math.isfinite(stock) and stock < 0)
            or (math.isfinite(consumption) and consumption < 0)
            or (cover is not None and cover < 0)
            or not math.isfinite(stock_out_days)
        ):
            alert_type = "invalid_data"
            severity = "warning"
            risk_level = "UNKNOWN"
            message = "Reported stock is negative. Verify the source record before acting."
        elif not math.isfinite(stock) or not math.isfinite(consumption) or (
            cover is not None and not math.isfinite(cover)
        ):
            alert_type = "cover_unavailable"
            severity = "warning"
            risk_level = "UNKNOWN"
            message = "Stock cover cannot be assessed because a stock or consumption value is invalid."
        elif consumption <= 0 or cover is None:
            alert_type = "cover_unavailable"
            severity = "warning"
            risk_level = "UNKNOWN"
            message = "Stock cover cannot be estimated because reported consumption is zero or unavailable."
        elif cover < 7:
            alert_type = "critical_stock"
            severity = "critical"
            risk_level = "CRITICAL"
            message = f"Estimated stock cover is below 7 days ({cover:.1f} days)."
        elif cover <= 14:
            alert_type = "low_stock"
            severity = "warning"
            risk_level = "MODERATE"
            message = f"Estimated stock cover is 7-14 days ({cover:.1f} days)."
        else:
            continue
        alerts.append(
            StockAlert(
                alert_id=_alert_id(facility, medicine_code, str(row["district"])),
                alert_type=alert_type,
                severity=severity,
                facility=facility,
                district=str(row["district"]),
                medicine=str(row["medicine"]),
                medicine_code=medicine_code,
                reporting_date=str(row["reporting_date"]),
                stock_units=stock if math.isfinite(stock) else None,
                daily_consumption=consumption if math.isfinite(consumption) else None,
                lead_time_days=cover,
                estimated_stock_after_7_days=estimate_stock_after_days(stock, consumption, 7),
                estimated_stock_after_14_days=estimate_stock_after_days(stock, consumption, 14),
                risk_level=risk_level,
                data_source=str(row["data_source"]),
                is_synthetic=bool(row["is_synthetic"]),
                provenance_status=str(
                    row.get(
                        "provenance_status",
                        "synthetic" if row["is_synthetic"] else "uploaded_unverified",
                    )
                ),
                message=message,
            )
        )
    return sorted(
        alerts,
        key=lambda alert: (
            -_SEVERITY_RANK[alert.severity],
            {
                "stockout": 0,
                "critical_stock": 1,
                "low_stock": 2,
                "cover_unavailable": 3,
                "invalid_data": 4,
            }[alert.alert_type],
            alert.lead_time_days if alert.lead_time_days is not None else math.inf,
            alert.facility.casefold(),
            alert.medicine_code.casefold(),
        ),
    )


def _recipients(value: str) -> list[str]:
    return [recipient.strip() for recipient in value.split(",") if recipient.strip()]


def _email_configuration(config: Settings) -> tuple[str, list[str]] | None:
    recipients = _recipients(config.alert_email_to)
    if not config.alert_smtp_host or not config.alert_email_from or not recipients:
        return None
    if bool(config.alert_smtp_username) != bool(config.alert_smtp_password):
        raise ValueError("SMTP username and password must either both be configured or both be empty.")
    if config.alert_smtp_username and not config.alert_smtp_starttls and config.alert_smtp_port != 465:
        raise ValueError("Authenticated SMTP requires STARTTLS or implicit TLS on port 465.")
    return config.alert_email_from, recipients


def _sms_configuration(config: Settings) -> tuple[str, list[str]] | None:
    recipients = _recipients(config.alert_sms_to)
    required = (
        config.alert_twilio_account_sid,
        config.alert_twilio_auth_token,
        config.alert_twilio_from,
    )
    if not all(required) or not recipients:
        return None
    return config.alert_twilio_from, recipients


def _should_send(
    severity: str | None,
    sent_at: datetime | None,
    current: StockAlert,
    now: datetime,
    cooldown: timedelta,
) -> bool:
    if severity is None or severity == "RECOVERED":
        return True
    if _SEVERITY_RANK[current.severity] > _SEVERITY_RANK.get(severity, 0):
        return True
    if sent_at is None:
        return True
    return now - sent_at.replace(tzinfo=timezone.utc) >= cooldown


def _message_body(items: list[dict[str, Any]]) -> str:
    lines = ["MediPredict stock alert digest", ""]
    for item in items:
        alert = item["alert"]
        if item["action"] == "recovery":
            lines.append(
                f"RECOVERED: {alert['facility']} / {alert['medicine']} "
                f"({alert['medicine_code']}); latest cover is now above 14 days."
            )
        else:
            lines.append(
                f"{alert['severity'].upper()}: {alert['facility']} / {alert['medicine']} "
                f"({alert['medicine_code']}) - {alert['message']} "
                f"Reported {alert['reporting_date']}; source={alert['data_source']}."
            )
    lines.extend(
        [
            "",
            "These are rule-based stock warnings from the latest reported snapshot, not forecasts.",
            "Verify the reported stock and consumption before taking action.",
        ]
    )
    return "\n".join(lines)


def _send_email(config: Settings, sender: str, recipients: list[str], body: str) -> None:
    message = EmailMessage()
    message["Subject"] = "MediPredict stock warning"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    if config.alert_smtp_port == 465 and not config.alert_smtp_starttls:
        client_factory = smtplib.SMTP_SSL
    else:
        client_factory = smtplib.SMTP
    with client_factory(config.alert_smtp_host, config.alert_smtp_port, timeout=15) as client:
        if config.alert_smtp_starttls:
            client.starttls()
        if config.alert_smtp_username:
            client.login(config.alert_smtp_username, config.alert_smtp_password)
        client.send_message(message)


def _send_sms(config: Settings, sender: str, recipients: list[str], body: str) -> None:
    if not config.alert_twilio_account_sid or not config.alert_twilio_auth_token:
        raise ValueError("Twilio credentials are incomplete.")
    message = body[:1500]
    for recipient in recipients:
        response = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{config.alert_twilio_account_sid}/Messages.json",
            data={"From": sender, "To": recipient, "Body": message},
            auth=(config.alert_twilio_account_sid, config.alert_twilio_auth_token),
            timeout=15,
        )
        response.raise_for_status()


def dispatch_stock_alerts(
    session: Session,
    rows: list[dict[str, Any]],
    alerts: list[StockAlert],
    *,
    config: Settings = settings,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not rows:
        return {
            "suppressed": True,
            "reason": "No current inventory rows are available.",
            "email": "not_sent",
            "sms": "not_sent",
        }
    if any(row.get("is_synthetic") is not False for row in rows):
        return {
            "suppressed": True,
            "reason": "External notifications are disabled unless every row is explicitly non-synthetic.",
            "email": "not_sent",
            "sms": "not_sent",
        }
    if any(row.get("data_source") != "real" for row in rows):
        return {
            "suppressed": True,
            "reason": "External notifications are disabled unless every row has data_source='real'.",
            "email": "not_sent",
            "sms": "not_sent",
        }

    current_time = now or datetime.now(timezone.utc)
    cooldown = timedelta(hours=config.alert_cooldown_hours)
    current_by_key = {alert.alert_id: alert for alert in alerts}
    known_keys = sorted({
        _alert_id(str(row["facility"]), str(row["medicine_code"]), str(row["district"]))
        for row in rows
    })
    states = {
        state.alert_key: state
        for state in session.query(AlertNotificationState).all()
    }
    try:
        email_config = _email_configuration(config)
        sms_config = _sms_configuration(config)
    except ValueError as exc:
        return {
            "suppressed": True,
            "reason": str(exc),
            "email": "invalid_configuration",
            "sms": "not_sent",
        }
    notification_items: dict[str, list[dict[str, Any]]] = {"email": [], "sms": []}

    for channel, configured in (("email", email_config), ("sms", sms_config)):
        if configured is None:
            continue
        severity_field = f"{channel}_severity"
        sent_at_field = f"{channel}_sent_at"
        for key in known_keys:
            state = states.get(key)
            if state is None:
                if key not in current_by_key:
                    continue
                state = AlertNotificationState(alert_key=key)
                states[key] = state
                session.add(state)
            prior_severity = getattr(state, severity_field)
            sent_at = getattr(state, sent_at_field)
            alert = current_by_key.get(key)
            if alert is not None:
                if _should_send(prior_severity, sent_at, alert, current_time, cooldown):
                    notification_items[channel].append(
                        {"alert_id": key, "action": "alert", "alert": alert.model_dump()}
                    )
            elif state is not None and prior_severity and prior_severity != "RECOVERED":
                row = next(
                    row for row in rows
                    if _alert_id(
                        str(row["facility"]), str(row["medicine_code"]), str(row["district"])
                    ) == key
                )
                notification_items[channel].append(
                    {
                        "alert_id": key,
                        "action": "recovery",
                        "alert": {
                            "facility": str(row["facility"]),
                            "medicine": str(row["medicine"]),
                            "medicine_code": str(row["medicine_code"]),
                        },
                    }
                )

    result: dict[str, Any] = {
        "suppressed": False,
        "active_alerts": len(alerts),
        "email": "not_configured" if email_config is None else "no_change",
        "sms": "not_configured" if sms_config is None else "no_change",
        "email_notifications": 0,
        "sms_notifications": 0,
    }
    for channel, channel_config, sender_function in (
        ("email", email_config, _send_email),
        ("sms", sms_config, _send_sms),
    ):
        items = notification_items[channel]
        if channel_config is None or not items:
            continue
        try:
            if channel == "email":
                sender, recipients = channel_config
                sender_function(config, sender, recipients, _message_body(items))
            else:
                sender, recipients = channel_config
                sender_function(config, sender, recipients, _message_body(items))
        except (OSError, requests.RequestException, smtplib.SMTPException, ValueError):
            result[channel] = "failed"
            result[f"{channel}_error"] = "Delivery failed; check provider configuration and service logs."
            continue

        result[channel] = "sent"
        result[f"{channel}_notifications"] = len(items)
        for item in items:
            state = states[item["alert_id"]]
            setattr(
                state,
                f"{channel}_severity",
                item["alert"]["severity"] if item["action"] == "alert" else "RECOVERED",
            )
            setattr(state, f"{channel}_sent_at", current_time.replace(tzinfo=None))
            state.updated_at = current_time.replace(tzinfo=None)
    session.commit()
    return result
