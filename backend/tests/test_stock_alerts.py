from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import pytest
from fastapi import HTTPException

from backend.app import alerts, main, ml_service
from backend.app.alerts import build_stock_alerts, dispatch_stock_alerts
from backend.app.config import Settings
from backend.app.database import Base


def _row(
    *,
    stock: float = 20,
    consumption: float = 2,
    cover: float | None = 10,
    synthetic: bool = False,
) -> dict:
    return {
        "facility": "Facility A",
        "district": "Gasabo",
        "medicine": "Medicine A",
        "medicine_code": "MED-1",
        "reporting_date": "2026-10-27",
        "stock_units": stock,
        "daily_consumption": consumption,
        "lead_time_days": cover,
        "risk_level": "MODERATE" if cover is not None and cover <= 14 else "STABLE",
        "data_source": "synthetic" if synthetic else "real",
        "is_synthetic": synthetic,
    }


def test_alerts_cover_stockout_critical_warning_and_unavailable_cover():
    rows = [
        _row(stock=0, consumption=0, cover=None),
        _row(stock=6, consumption=1, cover=6),
        _row(stock=28, consumption=2, cover=14),
        _row(stock=20, consumption=0, cover=None),
        _row(stock=-2, consumption=1, cover=-2),
        _row(stock=60, consumption=2, cover=30),
    ]

    result = build_stock_alerts(rows)

    assert [alert.alert_type for alert in result] == [
        "stockout",
        "critical_stock",
        "low_stock",
        "cover_unavailable",
        "invalid_data",
    ]
    assert [alert.severity for alert in result] == [
        "critical", "critical", "warning", "warning", "warning"
    ]
    assert result[0].risk_level == "CRITICAL"
    assert result[3].lead_time_days is None
    assert result[0].estimated_stock_after_7_days == 0
    assert result[1].estimated_stock_after_7_days == 0
    assert result[2].estimated_stock_after_7_days == 14
    assert result[2].estimated_stock_after_14_days == 0
    assert result[3].estimated_stock_after_7_days is None


@pytest.mark.parametrize(
    "event",
    [{"stockout_flag": "true"}, {"stock_out_days": 2}],
)
def test_recorded_stockout_fields_trigger_critical_alert(event):
    row = {**_row(stock=50, consumption=2, cover=25), **event}

    result = build_stock_alerts([row])

    assert len(result) == 1
    assert result[0].alert_type == "stockout"
    assert result[0].severity == "critical"


def test_missing_consumption_is_unknown_not_stable_and_stockout_stays_critical(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(ml_service.settings, "model_path", tmp_path / "missing.joblib")
    records = [
        {
            "facility": "A", "district": "Gasabo", "medicine": "M1",
            "medicine_code": "M1", "stock_units": 20, "daily_consumption": 0,
            "is_synthetic": True,
        },
        {
            "facility": "B", "district": "Gasabo", "medicine": "M1",
            "medicine_code": "M1", "stock_units": 0, "daily_consumption": 0,
            "is_synthetic": True,
        },
    ]

    assessed = ml_service.infer(records)

    assert assessed[0]["risk_level"] == "UNKNOWN"
    assert assessed[0]["lead_time_days"] is None
    assert assessed[1]["risk_level"] == "CRITICAL"
    assert assessed[1]["lead_time_days"] is None


def test_external_notifications_are_suppressed_for_synthetic_rows():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    row = _row(synthetic=True)
    with Session(engine) as session:
        result = dispatch_stock_alerts(
            session,
            [row],
            build_stock_alerts([row]),
            config=Settings(alert_email_to="ops@example.org"),
        )

    assert result["suppressed"] is True
    assert "non-synthetic" in result["reason"]


def test_external_notifications_are_suppressed_for_uploaded_source():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    row = {**_row(), "data_source": "uploaded"}
    with Session(engine) as session:
        result = dispatch_stock_alerts(
            session,
            [row],
            build_stock_alerts([row]),
            config=Settings(alert_email_to="ops@example.org"),
        )

    assert result["suppressed"] is True
    assert "data_source='real'" in result["reason"]


def test_alert_endpoint_requires_configured_admin_key(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main.settings, "admin_api_key", "configured-secret")
    with Session(engine) as session, pytest.raises(HTTPException) as error:
        main.dispatch_alert_notifications(None, session)

    assert error.value.status_code == 403
    assert error.value.detail == "Admin API key is missing or invalid."


def test_alert_list_endpoint_returns_latest_rule_based_warnings(monkeypatch):
    row = _row(stock=0, consumption=0, cover=None)
    monkeypatch.setattr(main, "load_rows", lambda: [row])

    result = asyncio.run(main.stock_alerts())

    assert len(result) == 1
    assert result[0].alert_type == "stockout"
    assert result[0].risk_level == "CRITICAL"


def test_notification_cooldown_and_escalation(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    config = Settings(
        alert_smtp_host="smtp.example.org",
        alert_email_from="alerts@example.org",
        alert_email_to="ops@example.org",
        alert_cooldown_hours=24,
    )
    sends: list[str] = []
    monkeypatch.setattr(alerts, "_send_email", lambda *args: sends.append(args[3]))
    current_time = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
    warning = _row(stock=20, consumption=2, cover=10)
    critical = _row(stock=10, consumption=2, cover=5)

    with Session(engine) as session:
        first = dispatch_stock_alerts(
            session, [warning], build_stock_alerts([warning]), config=config, now=current_time
        )
        repeated = dispatch_stock_alerts(
            session, [warning], build_stock_alerts([warning]), config=config,
            now=current_time.replace(hour=11),
        )
        escalated = dispatch_stock_alerts(
            session, [critical], build_stock_alerts([critical]), config=config,
            now=current_time.replace(hour=12),
        )

    assert first["email"] == "sent"
    assert repeated["email"] == "no_change"
    assert escalated["email"] == "sent"
    assert len(sends) == 2
    assert "WARNING" in sends[0]
    assert "CRITICAL" in sends[1]


def test_email_recovery_notification_is_sent_when_cover_stabilizes(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    config = Settings(
        alert_smtp_host="smtp.example.org",
        alert_email_from="alerts@example.org",
        alert_email_to="ops@example.org",
    )
    sends: list[str] = []
    monkeypatch.setattr(alerts, "_send_email", lambda *args: sends.append(args[3]))
    current_time = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
    warning = _row(stock=20, consumption=2, cover=10)
    stable = _row(stock=40, consumption=2, cover=20)

    with Session(engine) as session:
        dispatch_stock_alerts(
            session, [warning], build_stock_alerts([warning]), config=config, now=current_time
        )
        recovered = dispatch_stock_alerts(
            session, [stable], build_stock_alerts([stable]), config=config,
            now=current_time.replace(hour=11),
        )

    assert recovered["email"] == "sent"
    assert len(sends) == 2
    assert "RECOVERED" in sends[1]
