from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base


class AuthUser(Base):
    __tablename__ = "auth_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(20), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("auth_users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    facility_type: Mapped[str] = mapped_column(String(80), default="Health Center")
    district: Mapped[str] = mapped_column(String(100), index=True)
    province: Mapped[str] = mapped_column(String(100), default="")
    under5_population: Mapped[int] = mapped_column(Integer, default=0)
    poverty_rate: Mapped[float] = mapped_column(Float, default=0)
    malaria_prevalence: Mapped[float] = mapped_column(Float, default=0)
    stock_logs: Mapped[list["DailyStockLog"]] = relationship(back_populates="facility")

class Medicine(Base):
    __tablename__ = "medicines"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(240))
    safety_days: Mapped[int] = mapped_column(Integer, default=14)
    stock_logs: Mapped[list["DailyStockLog"]] = relationship(back_populates="medicine")

class DailyStockLog(Base):
    __tablename__ = "daily_stock_logs"
    __table_args__ = (UniqueConstraint("facility_id", "medicine_id", "reporting_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), index=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"), index=True)
    reporting_date: Mapped[str] = mapped_column(String(20), index=True)
    stock_units: Mapped[float] = mapped_column(Float)
    daily_consumption: Mapped[float] = mapped_column(Float)
    rainy_season: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    data_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    facility: Mapped[Facility] = relationship(back_populates="stock_logs")
    medicine: Mapped[Medicine] = relationship(back_populates="stock_logs")

class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), index=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    lead_time_days: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    is_synthetic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    data_source: Mapped[str | None] = mapped_column(String(32), nullable=True)

class AlertNotificationState(Base):
    __tablename__ = "alert_notification_states"
    alert_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    email_severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sms_severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sms_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DatasetRecord(Base):
    __tablename__ = "datasets"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    object_key: Mapped[str] = mapped_column(String(1024), unique=True)
    storage_backend: Mapped[str] = mapped_column(String(20))
    byte_size: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    date_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    data_frequency: Mapped[str] = mapped_column(String(12))
    is_synthetic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    data_source: Mapped[str] = mapped_column(String(80))
    uploader: Mapped[str | None] = mapped_column(String(160), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class DatasetEvent(Base):
    __tablename__ = "dataset_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.dataset_id"), index=True)
    dataset_sha256: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(24))
    actor_subject: Mapped[str | None] = mapped_column(String(160), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON)


class DatasetArchive(Base):
    __tablename__ = "dataset_archives"

    archive_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(1024), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    byte_size: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[str] = mapped_column(String(20))
    period_end: Mapped[str] = mapped_column(String(20))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ModelRelease(Base):
    __tablename__ = "model_releases"

    model_version: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.dataset_id"), nullable=True, index=True
    )
    source_dataset_sha256: Mapped[str] = mapped_column(String(64))
    artifact_key: Mapped[str] = mapped_column(String(1024), unique=True)
    model_sha256: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    model_validated: Mapped[bool] = mapped_column(Boolean)
    release_status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
