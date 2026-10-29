from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
from pathlib import Path
import io
import tempfile
import uuid

import pandas as pd
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .database import Base, engine, get_db
from . import models
from .alerts import build_stock_alerts, dispatch_stock_alerts
from .ml_service import (
    estimate_stock_after_days,
    infer,
    load_metrics,
    parse_is_synthetic,
    risk_from_lead_time,
)
from .provenance import (
    ProvenanceError,
    resolve_provenance,
    revoke_verification,
    verify_dataset,
)
from .storage import (
    ObjectStorageError,
    StorageConfigurationError,
    delete_object,
    read_dashboard_csv,
    read_object,
    write_object,
    write_verified_object,
)
from .schemas.api import (
    CsvAssessmentItem,
    CsvAssessmentResult,
    CsvValidationReport,
    DatasetDetail,
    ProvenanceResponse,
    StockAlert,
    Summary,
    RiskRecord,
    TransferCandidate,
    TrainingUploadResult,
    TrainingJobStatus,
    TrustMetrics,
)
from .validation import ValidationConfig, validate_inventory_csv

logger = logging.getLogger(__name__)
MAX_CSV_BYTES = 20 * 1024 * 1024
MAX_TRAINING_ARTIFACT_BYTES = 512 * 1024 * 1024
CSV_COLUMNS = {"facility_name": "facility", "district": "district", "province": "province", "facility_type": "facility_type", "medicine_code": "medicine_code", "medicine_name": "medicine", "end_of_month_stock_units": "stock_units", "avg_daily_consumption_units": "daily_consumption", "nisr_under_5_population": "under5_population", "nisr_poverty_rate_pct": "poverty_rate", "nisr_malaria_prevalence_pct": "malaria_prevalence", "rainy_season_active": "rainy_season", "reporting_month": "reporting_date"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.debug("Starting %s API.", app.title)
    if engine.dialect.name == "sqlite":
        logger.warning(
            "Using local SQLite; Aiven PostgreSQL is not configured. "
            "Set MEDIPREDICT_DATABASE_URL to an Aiven connection URL to enable it."
        )
    else:
        logger.info(
            "Database backend %s configured; connectivity will be checked on first use.",
            engine.dialect.name,
        )

    if not settings.database_enabled:
        logger.warning(
            "Database-backed features are disabled; "
            "set MEDIPREDICT_DATABASE_ENABLED=true to enable them."
        )

    if settings.storage_backend == "local":
        logger.warning(
            "Using local file storage; Cloudflare R2 is not configured. "
            "Set MEDIPREDICT_STORAGE_BACKEND=s3 and the R2 environment variables to enable it."
        )
    else:
        required_object_store_settings = {
            "MEDIPREDICT_OBJECT_STORE_BUCKET": settings.object_store_bucket,
            "MEDIPREDICT_OBJECT_STORE_ENDPOINT_URL": settings.object_store_endpoint_url,
            "MEDIPREDICT_OBJECT_STORE_ACCESS_KEY_ID": settings.object_store_access_key_id,
            "MEDIPREDICT_OBJECT_STORE_SECRET_ACCESS_KEY": (
                settings.object_store_secret_access_key
            ),
            "MEDIPREDICT_DASHBOARD_DATA_KEY": settings.dashboard_data_key,
        }
        missing_object_store_settings = [
            name for name, value in required_object_store_settings.items() if not value
        ]
        if missing_object_store_settings:
            logger.warning(
                "Cloudflare R2 is selected but configuration is incomplete; missing: %s.",
                ", ".join(missing_object_store_settings),
            )
        else:
            logger.info(
                "Cloudflare R2 configuration is present; connectivity will be checked "
                "on the first object request."
            )

    if settings.database_enabled and engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def load_rows() -> list[dict]:
    try:
        content = read_dashboard_csv()
    except StorageConfigurationError as exc:
        logger.error("Dashboard storage configuration error: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except ObjectStorageError as exc:
        logger.exception("Could not load dashboard data.")
        raise HTTPException(
            status_code=503,
            detail="Dashboard data is not available from configured storage.",
        ) from exc
    if content is None: return []
    df = pd.read_csv(io.BytesIO(content))
    if "is_synthetic" not in df.columns:
        raise RuntimeError("Operational CSV is missing required provenance column: is_synthetic")
    try:
        df["is_synthetic"] = [parse_is_synthetic(value) for value in df["is_synthetic"]]
    except ValueError as exc:
        raise RuntimeError(f"Operational CSV has invalid is_synthetic value: {exc}") from exc
    df = df.sort_values("reporting_month").groupby(["facility_name", "medicine_code"], as_index=False).tail(1)
    df = df.rename(columns=CSV_COLUMNS)
    rows = df.to_dict(orient="records")
    return infer(rows)

@app.get("/api/v1/health")
async def health(): return {"status": "ok", "service": settings.app_name}

def provenance_summary(
    rows: list[dict],
) -> tuple[str | None, bool | None, str]:
    if not rows:
        return None, None, "uploaded_unverified"
    flags = [bool(row["is_synthetic"]) for row in rows]
    return (
        "synthetic" if any(flags) else "real",
        any(flags),
        "synthetic" if all(flags) else "uploaded_unverified",
    )

@app.get("/api/v1/inventory/summary", response_model=Summary)
async def inventory_summary():
    rows = load_rows()
    if not rows: return Summary(facilities=0,districts=0,medicines=0,critical=0,moderate=0,stable=0,unknown=0,stock_units=0,reporting_date="—",data_source=None,is_synthetic=None,provenance_status="uploaded_unverified")
    data_source, is_synthetic, provenance_status = provenance_summary(rows)
    return Summary(facilities=len({r["facility"] for r in rows}), districts=len({r["district"] for r in rows}), medicines=len({r["medicine_code"] for r in rows}), critical=sum(r["risk_level"]=="CRITICAL" for r in rows), moderate=sum(r["risk_level"]=="MODERATE" for r in rows), stable=sum(r["risk_level"]=="STABLE" for r in rows), unknown=sum(r["risk_level"]=="UNKNOWN" for r in rows), stock_units=int(sum(r["stock_units"] for r in rows)), reporting_date=str(max(r["reporting_date"] for r in rows)),data_source=data_source,is_synthetic=is_synthetic, provenance_status=provenance_status)

@app.get("/api/v1/predictions/risk-register", response_model=list[RiskRecord])
async def risk_register(risk: str | None = Query(default=None), district: str | None = Query(default=None), search: str | None = Query(default=None), limit: int = Query(default=500, ge=1, le=5000)):
    rows = load_rows()
    if risk: rows = [r for r in rows if r["risk_level"] == risk.upper()]
    if district: rows = [r for r in rows if r["district"].casefold() == district.casefold()]
    if search: rows = [r for r in rows if search.casefold() in (r["facility"]+r["medicine"]+r["district"]).casefold()]
    return sorted(rows, key=lambda r: (0 if r["risk_level"]=="CRITICAL" else 1 if r["risk_level"]=="MODERATE" else 2 if r["risk_level"]=="STABLE" else 3, r["lead_time_days"] if r["lead_time_days"] is not None else float("inf")))[:limit]

@app.get("/api/v1/alerts", response_model=list[StockAlert])
async def stock_alerts():
    return build_stock_alerts(load_rows())

@app.post("/api/v1/alerts/dispatch")
def dispatch_alert_notifications(
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Alert notification dispatch")
    rows = load_rows()
    alerts = build_stock_alerts(rows)
    return dispatch_stock_alerts(db, rows, alerts)

def _validation_config() -> ValidationConfig:
    return ValidationConfig(
        minimum_records_per_facility_item=(
            settings.training_min_records
            if settings.data_frequency == "daily"
            else settings.training_min_records_monthly
        ),
        minimum_facility_items=settings.training_min_facility_items,
        data_frequency=settings.data_frequency,
    )


async def _read_csv(file: UploadFile) -> tuple[bytes, pd.DataFrame]:
    if not file.filename or Path(file.filename).suffix.casefold() != ".csv":
        raise HTTPException(400, "Upload a .csv file")
    try:
        content = await file.read(MAX_CSV_BYTES + 1)
        if len(content) > MAX_CSV_BYTES:
            raise HTTPException(413, "CSV must be smaller than 20 MB")
        frame = pd.read_csv(
            io.BytesIO(content),
            dtype=str,
            keep_default_na=False,
        )
        return content, frame
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422, f"Could not parse CSV: {exc}") from exc


def _validation_report(
    frame: pd.DataFrame,
    purpose: str,
) -> CsvValidationReport:
    return CsvValidationReport.model_validate(
        validate_inventory_csv(
            frame,
            purpose=purpose,
            config=_validation_config(),
        )
    )


def _assessment_result(
    frame: pd.DataFrame,
    report: CsvValidationReport,
) -> CsvAssessmentResult:
    if not report.valid:
        raise HTTPException(
            status_code=422,
            detail={"message": "CSV validation failed.", "validation": report.model_dump()},
        )

    items = []
    confidence_note = (
        "Stock-cover estimate uses reported stock and average daily consumption. "
        "Assumes constant consumption and no incoming receipts; not a probability."
    )
    for _, row in frame.iterrows():
        stock = float(row["stock_on_hand"])
        consumed = float(row["units_consumed"])
        lead_time = stock / consumed if consumed > 0 else None
        stock_after_7_days = estimate_stock_after_days(stock, consumed, 7)
        stock_after_14_days = estimate_stock_after_days(stock, consumed, 14)
        explicit_stockout = (
            parse_is_synthetic(row["stockout_flag"])
            if "stockout_flag" in frame.columns and row["stockout_flag"].strip()
            else False
        )
        risk = (
            "CRITICAL" if stock <= 0 or explicit_stockout
            else risk_from_lead_time(lead_time)
        )
        synthetic_value = row.get("is_synthetic")
        synthetic = (
            parse_is_synthetic(synthetic_value)
            if synthetic_value is not None and str(synthetic_value).strip()
            else None
        )
        explicit_stockout = explicit_stockout or stock == 0
        items.append(
            CsvAssessmentItem(
                facility_id=row["facility_id"].strip(),
                item_id=row["item_id"].strip(),
                date=row["date"],
                stock_on_hand=stock,
                units_consumed=consumed,
                units_received=float(row["units_received"]),
                stockout_flag=explicit_stockout,
                lead_time_days=lead_time,
                estimated_stock_after_7_days=stock_after_7_days,
                estimated_stock_after_14_days=stock_after_14_days,
                risk_level=risk,
                confidence=None,
                confidence_note=confidence_note,
                method="rule_based_fallback",
                model_version=None,
                model_validated=False,
                data_source="uploaded",
                is_synthetic=synthetic,
                provenance_status="synthetic" if synthetic else "uploaded_unverified",
                facility_type=row.get("facility_type") or None,
                region=row.get("region") or None,
                reorder_level=(
                    float(row["reorder_level"])
                    if row.get("reorder_level", "").strip()
                    else None
                ),
                stockout_flag_assumption=(
                    None
                    if "stockout_flag" in frame.columns
                    else "Assumed stockout_flag = (stock_on_hand == 0)."
                ),
            )
        )

    synthetic_values = {item.is_synthetic for item in items}
    return CsvAssessmentResult(
        records_received=len(items),
        predictions=len(items),
        critical=sum(item.risk_level == "CRITICAL" for item in items),
        moderate=sum(item.risk_level == "MODERATE" for item in items),
        stable=sum(item.risk_level == "STABLE" for item in items),
        unknown=sum(item.risk_level == "UNKNOWN" for item in items),
        method="rule_based_fallback",
        model_version=None,
        model_validated=False,
        data_source="uploaded",
        is_synthetic=next(iter(synthetic_values)) if len(synthetic_values) == 1 else None,
        provenance_status=(
            "synthetic" if synthetic_values == {True} else "uploaded_unverified"
        ),
        confidence_note=confidence_note,
        validation=report,
        items=items,
    )


def _store_assessment_upload(
    content: bytes,
    report: CsvValidationReport,
) -> None:
    digest = hashlib.sha256(content).hexdigest()
    prefix = f"assessments/{digest}"
    metadata = {
        "sha256": digest,
        "byte_size": len(content),
        "row_count": report.row_count,
        "date_range": report.date_range,
        "is_synthetic": report.is_synthetic,
        "data_source": "uploaded",
        "provenance_status": report.provenance_status,
    }
    try:
        write_verified_object(
            f"{prefix}/data.csv",
            content,
            max_bytes=MAX_CSV_BYTES,
        )
        write_verified_object(
            f"{prefix}/metadata.json",
            json.dumps(metadata, sort_keys=True).encode("utf-8"),
            max_bytes=MAX_CSV_BYTES,
        )
    except (ObjectStorageError, StorageConfigurationError) as exc:
        logger.exception("Could not persist assessed CSV %s.", digest)
        raise HTTPException(
            503,
            "The validated CSV could not be saved to configured storage.",
        ) from exc


@app.post("/api/v1/data/assess-csv", response_model=CsvAssessmentResult)
async def assess_csv(file: UploadFile = File(...)):
    content, frame = await _read_csv(file)
    report = _validation_report(frame, "assessment")
    if report.data_frequency == "monthly":
        raise HTTPException(
            status_code=422,
            detail=(
                "Rule-based CSV assessment currently supports daily-frequency data only. "
                "Monthly data can be validated and prepared for feature analysis."
            ),
        )
    result = _assessment_result(frame, report)
    _store_assessment_upload(content, report)
    return result


@app.post("/api/v1/data/validate-csv", response_model=CsvValidationReport)
async def validate_csv(
    file: UploadFile = File(...),
    purpose: str = Query(default="assessment", pattern="^(assessment|training)$"),
):
    _, frame = await _read_csv(file)
    return _validation_report(frame, purpose)


def _require_admin(api_key: str | None, *, operation: str = "Training upload") -> None:
    if not settings.admin_api_key:
        raise HTTPException(503, f"{operation} is disabled: admin API key is not configured.")
    if api_key is None or not hmac.compare_digest(api_key, settings.admin_api_key):
        raise HTTPException(403, "Admin API key is missing or invalid.")


def _dataset_object_key(dataset_id: str) -> str:
    return f"v1/{dataset_id}/data.csv"


def _store_dataset_event(
    db: Session,
    *,
    dataset_id: str,
    dataset_sha256: str,
    event_type: str,
    actor_subject: str | None,
    details: dict,
) -> None:
    db.add(
        models.DatasetEvent(
            event_id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            dataset_sha256=dataset_sha256,
            event_type=event_type,
            actor_subject=actor_subject,
            details=details,
        )
    )


def _dataset_record(dataset_id: str, db: Session) -> models.DatasetRecord | None:
    return db.get(models.DatasetRecord, dataset_id)


@contextmanager
def _dataset_workspace(record: models.DatasetRecord, db: Session):
    """Materialize a bounded, temporary compatibility workspace for provenance checks."""
    temporary_directory = tempfile.TemporaryDirectory(prefix="medipredict-dataset-")
    root = Path(temporary_directory.name)
    dataset_dir = root / "v1" / record.dataset_id
    dataset_dir.mkdir(parents=True)
    try:
        content = read_object(
            record.object_key,
            max_bytes=MAX_CSV_BYTES,
            backend=record.storage_backend,
        )
        if hashlib.sha256(content).hexdigest() != record.sha256:
            raise ObjectStorageError("Stored dataset object failed its SHA-256 check.")
        data_path = dataset_dir / "data.csv"
        data_path.write_bytes(content)
        metadata = dict(record.metadata_json)
        metadata.update(
            dataset_id=record.dataset_id,
            sha256=record.sha256,
            uploaded_at_utc=record.uploaded_at.isoformat()
            if record.uploaded_at
            else None,
        )
        (dataset_dir / "metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )

        events = db.scalars(
            select(models.DatasetEvent)
            .where(models.DatasetEvent.dataset_id == record.dataset_id)
            .order_by(models.DatasetEvent.occurred_at, models.DatasetEvent.event_id)
        ).all()
        history = []
        for event in events:
            if event.event_type not in {"verification", "revocation"}:
                continue
            details = dict(event.details)
            evidence_key = details.get("evidence_object_key")
            evidence_hash = details.get("evidence_file_sha256")
            if evidence_key and evidence_hash:
                evidence = read_object(
                    evidence_key,
                    max_bytes=MAX_CSV_BYTES,
                    backend=details.get("evidence_storage_backend", record.storage_backend),
                )
                if hashlib.sha256(evidence).hexdigest() != evidence_hash:
                    raise ObjectStorageError("Stored verification evidence failed its checksum.")
                evidence_dir = dataset_dir / "evidence"
                evidence_dir.mkdir(exist_ok=True)
                (evidence_dir / evidence_hash).write_bytes(evidence)
            history.append(details)
        if history:
            (dataset_dir / "verification.json").write_text(
                "".join(
                    json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
                    for item in history
                ),
                encoding="utf-8",
            )
        yield root
    finally:
        temporary_directory.cleanup()


def _resolve_stored_provenance(
    record: models.DatasetRecord, db: Session
) -> dict:
    try:
        with _dataset_workspace(record, db) as workspace:
            return resolve_provenance(record.dataset_id, workspace)
    except (ObjectStorageError, StorageConfigurationError) as exc:
        logger.exception("Could not read dataset %s from storage.", record.dataset_id)
        raise HTTPException(
            503, "Dataset files are unavailable from configured storage."
        ) from exc


@app.post("/api/v1/data/training-upload", response_model=TrainingUploadResult)
async def training_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    x_uploader: str | None = Header(default=None, alias="X-Uploader"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key)
    content, frame = await _read_csv(file)
    report = _validation_report(frame, "training")
    if not report.valid:
        raise HTTPException(
            status_code=422,
            detail={"message": "Training CSV validation failed.", "validation": report.model_dump()},
        )

    dataset_id = f"v1-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex}"
    digest = hashlib.sha256(content).hexdigest()
    synthetic = report.is_synthetic
    uploaded_at = datetime.now(timezone.utc)
    uploader = (x_uploader or "admin").strip()[:160]
    uploader_identity = (x_uploader or "").strip()[:160] or None
    object_key = _dataset_object_key(dataset_id)
    metadata = {
        "dataset_id": dataset_id,
        "sha256": digest,
        "uploader": uploader,
        "uploader_identity": uploader_identity,
        "uploaded_at_utc": uploaded_at.isoformat(),
        "row_count": report.row_count,
        "date_range": report.date_range,
        "data_frequency": report.data_frequency,
        "is_synthetic": synthetic,
        "data_source": "uploaded",
    }
    record = models.DatasetRecord(
        dataset_id=dataset_id,
        sha256=digest,
        object_key=object_key,
        storage_backend=settings.storage_backend,
        byte_size=len(content),
        row_count=report.row_count,
        date_start=report.date_range.get("start"),
        date_end=report.date_range.get("end"),
        data_frequency=report.data_frequency,
        is_synthetic=synthetic,
        data_source="uploaded",
        uploader=uploader,
        uploaded_at=uploaded_at,
        metadata_json=metadata,
    )
    metadata_path: Path | None = None
    object_written = False
    try:
        write_object(object_key, content)
        object_written = True
        stored_content = read_object(
            object_key,
            max_bytes=MAX_CSV_BYTES,
            backend=settings.storage_backend,
        )
        if hashlib.sha256(stored_content).hexdigest() != digest:
            raise ObjectStorageError("Stored dataset failed its SHA-256 check.")
        if settings.storage_backend == "local":
            metadata_path = settings.uploads_path / "v1" / dataset_id / "metadata.json"
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        db.add(record)
        _store_dataset_event(
            db,
            dataset_id=dataset_id,
            dataset_sha256=digest,
            event_type="upload",
            actor_subject=uploader_identity,
            details={"byte_size": len(content), "row_count": report.row_count},
        )
        _store_dataset_event(
            db,
            dataset_id=dataset_id,
            dataset_sha256=digest,
            event_type="training_queued",
            actor_subject="system",
            details={"is_synthetic": synthetic},
        )
        db.commit()
    except (ObjectStorageError, StorageConfigurationError) as exc:
        db.rollback()
        if object_written:
            try:
                delete_object(object_key, backend=settings.storage_backend)
            except (ObjectStorageError, StorageConfigurationError):
                logger.exception("Failed to remove a dataset object after upload failure.")
        if metadata_path is not None:
            try:
                metadata_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Failed to remove local dataset metadata after upload failure.")
        logger.exception("Could not store uploaded dataset.")
        raise HTTPException(
            503, "Dataset could not be saved to configured storage."
        ) from exc
    except Exception as exc:
        db.rollback()
        try:
            delete_object(object_key)
        except (ObjectStorageError, StorageConfigurationError):
            logger.exception("Failed to remove an unregistered dataset object.")
        if metadata_path is not None:
            try:
                metadata_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Failed to remove unregistered local dataset metadata.")
        logger.exception("Could not register uploaded dataset.")
        raise HTTPException(503, "Dataset metadata could not be saved.") from exc

    background_tasks.add_task(_run_automatic_training, dataset_id)
    return TrainingUploadResult(
        dataset_id=dataset_id,
        sha256=digest,
        row_count=report.row_count,
        date_range=report.date_range,
        data_frequency=report.data_frequency,
        is_synthetic=synthetic,
        data_source="uploaded",
        metadata_path=(
            f"database://datasets/{dataset_id}"
            if settings.storage_backend == "s3"
            else (settings.uploads_path / "v1" / dataset_id / "metadata.json")
            .relative_to(settings.uploads_path)
            .as_posix()
        ),
        provenance_status=_resolve_stored_provenance(record, db)["provenance_status"],
        verification_summary=None,
        training_status="queued",
    )


def _latest_training_event(dataset_id: str, db: Session) -> models.DatasetEvent | None:
    return db.scalars(
        select(models.DatasetEvent)
        .where(
            models.DatasetEvent.dataset_id == dataset_id,
            models.DatasetEvent.event_type.in_(
                (
                    "training_queued",
                    "training_started",
                    "training_completed",
                    "training_failed",
                )
            ),
        )
        .order_by(models.DatasetEvent.occurred_at.desc(), models.DatasetEvent.event_id.desc())
        .limit(1)
    ).first()


def _training_status_fields(
    dataset_id: str,
    db: Session,
) -> dict[str, object]:
    event = _latest_training_event(dataset_id, db)
    if event is None:
        return {}
    status_by_event = {
        "training_queued": "queued",
        "training_started": "running",
        "training_completed": "completed",
        "training_failed": "failed",
    }
    return {
        "training_status": status_by_event[event.event_type],
        "candidate_model_version": event.details.get("model_version"),
        "candidate_model_validated": event.details.get("model_validated"),
        "training_error": event.details.get("error"),
    }


def _dataset_response(dataset_id: str, db: Session) -> DatasetDetail:
    record = _dataset_record(dataset_id, db)
    if record is not None:
        metadata = record.metadata_json
        provenance = _resolve_stored_provenance(record, db)
        date_range = {
            "start": record.date_start,
            "end": record.date_end,
        }
        return DatasetDetail(
            dataset_id=record.dataset_id,
            sha256=record.sha256,
            row_count=record.row_count,
            date_range=date_range,
            data_frequency=record.data_frequency,
            is_synthetic=record.is_synthetic,
            data_source="uploaded",
            uploader=record.uploader,
            uploaded_at_utc=record.uploaded_at.isoformat()
            if record.uploaded_at
            else metadata.get("uploaded_at_utc"),
            provenance_status=provenance["provenance_status"],
            verification=provenance["verification"],
            verification_summary=provenance["verification_summary"],
            warning=provenance["warning"],
            **_training_status_fields(dataset_id, db),
        )

    dataset_dir = settings.uploads_path / "v1" / dataset_id
    metadata_path = dataset_dir / "metadata.json"
    if not metadata_path.is_file():
        raise HTTPException(404, "Dataset not found.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        provenance = resolve_provenance(dataset_id, settings.uploads_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (OSError, json.JSONDecodeError, ProvenanceError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return DatasetDetail(
        dataset_id=dataset_id,
        sha256=metadata.get("sha256") or None,
        row_count=metadata.get("row_count"),
        date_range=metadata.get("date_range") or {"start": None, "end": None},
        data_frequency=metadata.get("data_frequency"),
        is_synthetic=metadata.get("is_synthetic"),
        data_source="uploaded",
        uploader=metadata.get("uploader") or None,
        uploaded_at_utc=metadata.get("uploaded_at_utc") or None,
        provenance_status=provenance["provenance_status"],
        verification=provenance["verification"],
        verification_summary=provenance["verification_summary"],
        warning=provenance["warning"],
        **_training_status_fields(dataset_id, db),
    )


def _provenance_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(404, str(exc))
    return HTTPException(422, str(exc))


@app.get("/api/v1/data/datasets", response_model=list[DatasetDetail])
async def list_datasets(
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Dataset listing")
    records = db.scalars(
        select(models.DatasetRecord).order_by(models.DatasetRecord.uploaded_at.desc())
    ).all()
    dataset_ids = {record.dataset_id for record in records}
    results = [_dataset_response(record.dataset_id, db) for record in records]
    root = settings.uploads_path / "v1"
    if not root.exists():
        return results
    results.extend(
        _dataset_response(directory.name, db)
        for directory in sorted(root.iterdir())
        if directory.is_dir() and directory.name not in dataset_ids
    )
    return results


@app.get("/api/v1/data/datasets/{dataset_id}/download")
async def download_registered_dataset(
    dataset_id: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Dataset download")
    record = _dataset_record(dataset_id, db)
    if record is None:
        raise HTTPException(404, "Registered dataset not found.")
    try:
        content = read_object(
            record.object_key,
            max_bytes=MAX_CSV_BYTES,
            backend=record.storage_backend,
        )
    except (ObjectStorageError, StorageConfigurationError) as exc:
        logger.exception("Could not retrieve registered dataset %s.", dataset_id)
        raise HTTPException(503, "Dataset is unavailable from configured storage.") from exc
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise HTTPException(503, "Dataset failed SHA-256 verification.")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{dataset_id}.csv"'},
    )


@app.get("/api/v1/data/archives")
async def list_dataset_archives(
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Dataset archive listing")
    records = db.scalars(
        select(models.DatasetArchive).order_by(models.DatasetArchive.created_at.desc())
    ).all()
    return [
        {
            "archive_id": record.archive_id,
            "source_name": record.source_name,
            "object_key": record.object_key,
            "sha256": record.sha256,
            "byte_size": record.byte_size,
            "row_count": record.row_count,
            "period_start": record.period_start,
            "period_end": record.period_end,
            "is_synthetic": record.is_synthetic,
            "provenance_status": "synthetic" if record.is_synthetic else "uploaded_unverified",
            "metadata": record.metadata_json,
        }
        for record in records
    ]


@app.get("/api/v1/data/archives/{archive_id}/download")
async def download_dataset_archive(
    archive_id: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Dataset archive download")
    record = db.get(models.DatasetArchive, archive_id)
    if record is None:
        raise HTTPException(404, "Dataset archive not found.")
    try:
        content = read_object(
            record.object_key,
            max_bytes=MAX_CSV_BYTES,
            backend="s3",
        )
    except (ObjectStorageError, StorageConfigurationError) as exc:
        logger.exception("Could not retrieve dataset archive %s.", archive_id)
        raise HTTPException(503, "Dataset archive is unavailable from configured storage.") from exc
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise HTTPException(503, "Dataset archive failed SHA-256 verification.")
    filename = Path(record.source_name).name.replace('"', "")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/data/archives/{archive_id}/manifest")
async def download_dataset_archive_manifest(
    archive_id: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Dataset archive manifest download")
    record = db.get(models.DatasetArchive, archive_id)
    if record is None:
        raise HTTPException(404, "Dataset archive not found.")
    manifest_key = record.metadata_json.get("manifest_object_key")
    manifest_sha256 = record.metadata_json.get("manifest_sha256")
    if not isinstance(manifest_key, str) or not isinstance(manifest_sha256, str):
        raise HTTPException(404, "Dataset archive manifest is not registered.")
    try:
        content = read_object(
            manifest_key,
            max_bytes=MAX_CSV_BYTES,
            backend="s3",
        )
    except (ObjectStorageError, StorageConfigurationError) as exc:
        logger.exception("Could not retrieve dataset archive manifest %s.", archive_id)
        raise HTTPException(503, "Dataset archive manifest is unavailable from configured storage.") from exc
    if hashlib.sha256(content).hexdigest() != manifest_sha256:
        raise HTTPException(503, "Dataset archive manifest failed SHA-256 verification.")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{archive_id}.metadata.json"'},
    )


@app.get("/api/v1/models")
async def list_model_releases(
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Model registry listing")
    records = db.scalars(
        select(models.ModelRelease).order_by(models.ModelRelease.created_at.desc())
    ).all()
    return [
        {
            "model_version": record.model_version,
            "source_dataset_id": record.source_dataset_id,
            "source_dataset_sha256": record.source_dataset_sha256,
            "model_sha256": record.model_sha256,
            "model_validated": record.model_validated,
            "is_synthetic": record.is_synthetic,
            "release_status": record.release_status,
            "created_at": record.created_at,
            "artifact_key": record.artifact_key,
            "feature_dataset_id": record.metadata_json.get("feature_dataset_id"),
            "feature_table_sha256": record.metadata_json.get("feature_table_sha256"),
        }
        for record in records
    ]


def _download_model_artifact(
    release: models.ModelRelease,
    *,
    key_field: str,
    hash_field: str,
    filename: str,
) -> Response:
    metadata = release.metadata_json
    object_key = metadata.get(key_field)
    expected_hash = metadata.get(hash_field)
    if not isinstance(object_key, str) or not isinstance(expected_hash, str):
        raise HTTPException(404, "Requested model artifact is not registered.")
    try:
        content = read_object(
            object_key,
            max_bytes=MAX_TRAINING_ARTIFACT_BYTES,
            backend=metadata.get("storage_backend", "s3"),
        )
    except (ObjectStorageError, StorageConfigurationError) as exc:
        logger.exception(
            "Could not retrieve artifact for model version %s.",
            release.model_version,
        )
        raise HTTPException(503, "Model artifact is unavailable from configured storage.") from exc
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise HTTPException(503, "Model artifact failed SHA-256 verification.")
    safe_version = "".join(
        character for character in release.model_version if character.isalnum() or character in "-_"
    )
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{safe_version}-{filename}.zip"'
            )
        },
    )


@app.get("/api/v1/models/{model_version}/artifacts")
async def download_model_artifacts(
    model_version: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Model artifact download")
    release = db.get(models.ModelRelease, model_version)
    if release is None:
        raise HTTPException(404, "Model version not found.")
    return _download_model_artifact(
        release,
        key_field="model_bundle_key",
        hash_field="model_bundle_sha256",
        filename="candidate",
    )


@app.get("/api/v1/models/{model_version}/features")
async def download_model_features(
    model_version: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Feature artifact download")
    release = db.get(models.ModelRelease, model_version)
    if release is None:
        raise HTTPException(404, "Model version not found.")
    return _download_model_artifact(
        release,
        key_field="feature_bundle_key",
        hash_field="feature_bundle_sha256",
        filename="features",
    )


@app.get("/api/v1/data/datasets/{dataset_id}/provenance", response_model=ProvenanceResponse)
async def dataset_provenance(
    dataset_id: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Dataset provenance")
    record = _dataset_record(dataset_id, db)
    if record is not None:
        return _resolve_stored_provenance(record, db)
    try:
        return resolve_provenance(dataset_id, settings.uploads_path)
    except (FileNotFoundError, ProvenanceError) as exc:
        raise _provenance_http_error(exc) from exc


@app.get("/api/v1/data/datasets/{dataset_id}", response_model=DatasetDetail)
async def dataset_detail(
    dataset_id: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Dataset detail")
    return _dataset_response(dataset_id, db)


@app.get(
    "/api/v1/data/datasets/{dataset_id}/training-status",
    response_model=TrainingJobStatus,
)
async def dataset_training_status(
    dataset_id: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Training status")
    record = _dataset_record(dataset_id, db)
    if record is None:
        raise HTTPException(404, "Registered dataset not found.")
    event = _latest_training_event(dataset_id, db)
    if event is None:
        raise HTTPException(404, "No automatic training job is registered for this dataset.")
    status_by_event = {
        "training_queued": "queued",
        "training_started": "running",
        "training_completed": "completed",
        "training_failed": "failed",
    }
    return TrainingJobStatus(
        dataset_id=dataset_id,
        status=status_by_event[event.event_type],
        model_version=event.details.get("model_version"),
        model_validated=event.details.get("model_validated"),
        is_synthetic=event.details.get("is_synthetic", record.is_synthetic),
        error=event.details.get("error"),
        updated_at=event.occurred_at.isoformat(),
    )


def _run_automatic_training(dataset_id: str) -> None:
    from .database import SessionLocal
    from ml.train_registered_dataset import train_registered_dataset

    with SessionLocal() as db:
        record = _dataset_record(dataset_id, db)
        if record is None:
            logger.error("Automatic training has no registered dataset: %s", dataset_id)
            return
        dataset_hash = record.sha256
        _store_dataset_event(
            db,
            dataset_id=dataset_id,
            dataset_sha256=dataset_hash,
            event_type="training_started",
            actor_subject="system",
            details={"is_synthetic": record.is_synthetic},
        )
        db.commit()
        try:
            release = train_registered_dataset(dataset_id, db)
        except Exception as exc:
            db.rollback()
            logger.exception("Automatic training failed for dataset %s.", dataset_id)
            _store_dataset_event(
                db,
                dataset_id=dataset_id,
                dataset_sha256=dataset_hash,
                event_type="training_failed",
                actor_subject="system",
                details={
                    "is_synthetic": record.is_synthetic,
                    "error": str(exc)[:1000],
                },
            )
            db.commit()
            return
        _store_dataset_event(
            db,
            dataset_id=dataset_id,
            dataset_sha256=dataset_hash,
            event_type="training_completed",
            actor_subject="system",
            details={
                "model_version": release.model_version,
                "model_validated": release.model_validated,
                "is_synthetic": release.is_synthetic,
                "release_status": release.release_status,
            },
        )
        db.commit()


@app.post(
    "/api/v1/data/datasets/{dataset_id}/verify",
    response_model=ProvenanceResponse,
)
async def verify_uploaded_dataset(
    dataset_id: str,
    source_id: str = Form(...),
    verification_method: str = Form(...),
    verification_reference: str = Form(...),
    reporting_period_start: str = Form(...),
    reporting_period_end: str = Form(...),
    evidence_file: UploadFile | None = File(default=None),
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    x_admin_identity: str | None = Header(default=None, alias="X-Admin-Identity"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Dataset verification")
    evidence: bytes | None = None
    if evidence_file is not None:
        evidence = await evidence_file.read(MAX_CSV_BYTES + 1)
        if len(evidence) > MAX_CSV_BYTES:
            raise HTTPException(413, "Evidence file must be smaller than 20 MB.")
    record = _dataset_record(dataset_id, db)
    if record is not None:
        evidence_key: str | None = None
        try:
            with _dataset_workspace(record, db) as workspace:
                result = verify_dataset(
                    dataset_id,
                    workspace,
                    source_id=source_id,
                    verification_method=verification_method,
                    verification_reference=verification_reference,
                    reporting_period_start=reporting_period_start,
                    reporting_period_end=reporting_period_end,
                    verified_by=x_admin_identity,
                    evidence_file=evidence,
                )
                history_path = workspace / "v1" / dataset_id / "verification.json"
                event_record = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])

            if evidence is not None:
                evidence_hash = event_record["evidence_file_sha256"]
                evidence_key = (
                    f"v1/{dataset_id}/evidence/{uuid.uuid4().hex}/{evidence_hash}"
                )
                write_object(
                    evidence_key,
                    evidence,
                    backend=record.storage_backend,
                )
                event_record["evidence_object_key"] = evidence_key
                event_record["evidence_storage_backend"] = record.storage_backend
            _store_dataset_event(
                db,
                dataset_id=dataset_id,
                dataset_sha256=record.sha256,
                event_type="verification",
                actor_subject=x_admin_identity,
                details=event_record,
            )
            db.commit()
            return result
        except (FileNotFoundError, ProvenanceError) as exc:
            db.rollback()
            raise _provenance_http_error(exc) from exc
        except (ObjectStorageError, StorageConfigurationError) as exc:
            db.rollback()
            if evidence_key:
                try:
                    delete_object(evidence_key, backend=record.storage_backend)
                except (ObjectStorageError, StorageConfigurationError):
                    logger.exception("Could not clean up unregistered verification evidence.")
            logger.exception("Could not persist dataset verification.")
            raise HTTPException(503, "Dataset verification could not be saved.") from exc
        except Exception as exc:
            db.rollback()
            if evidence_key:
                try:
                    delete_object(evidence_key, backend=record.storage_backend)
                except (ObjectStorageError, StorageConfigurationError):
                    logger.exception("Could not clean up unregistered verification evidence.")
            logger.exception("Could not persist dataset verification.")
            raise HTTPException(503, "Dataset verification could not be saved.") from exc
    try:
        return verify_dataset(
            dataset_id,
            settings.uploads_path,
            source_id=source_id,
            verification_method=verification_method,
            verification_reference=verification_reference,
            reporting_period_start=reporting_period_start,
            reporting_period_end=reporting_period_end,
            verified_by=x_admin_identity,
            evidence_file=evidence,
        )
    except (FileNotFoundError, ProvenanceError) as exc:
        raise _provenance_http_error(exc) from exc


@app.post(
    "/api/v1/data/datasets/{dataset_id}/revoke-verification",
    response_model=ProvenanceResponse,
)
async def revoke_uploaded_dataset_verification(
    dataset_id: str,
    reason: str = Form(...),
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    x_admin_identity: str | None = Header(default=None, alias="X-Admin-Identity"),
    db: Session = Depends(get_db),
):
    _require_admin(x_admin_api_key, operation="Verification revocation")
    record = _dataset_record(dataset_id, db)
    if record is not None:
        try:
            with _dataset_workspace(record, db) as workspace:
                result = revoke_verification(
                    dataset_id,
                    workspace,
                    reason=reason,
                    revoked_by=x_admin_identity,
                )
                history_path = workspace / "v1" / dataset_id / "verification.json"
                event_record = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
            _store_dataset_event(
                db,
                dataset_id=dataset_id,
                dataset_sha256=record.sha256,
                event_type="revocation",
                actor_subject=x_admin_identity,
                details=event_record,
            )
            db.commit()
            return result
        except (FileNotFoundError, ProvenanceError) as exc:
            db.rollback()
            raise _provenance_http_error(exc) from exc
        except (ObjectStorageError, StorageConfigurationError) as exc:
            db.rollback()
            logger.exception("Could not persist verification revocation.")
            raise HTTPException(503, "Verification revocation could not be saved.") from exc
        except Exception as exc:
            db.rollback()
            logger.exception("Could not persist verification revocation.")
            raise HTTPException(503, "Verification revocation could not be saved.") from exc
    try:
        return revoke_verification(
            dataset_id,
            settings.uploads_path,
            reason=reason,
            revoked_by=x_admin_identity,
        )
    except (FileNotFoundError, ProvenanceError) as exc:
        raise _provenance_http_error(exc) from exc


@app.post(
    "/api/v1/data/upload-csv",
    response_model=CsvAssessmentResult,
    deprecated=True,
)
async def upload_csv(file: UploadFile = File(...)):
    logger.warning("Deprecated endpoint /api/v1/data/upload-csv used; use /assess-csv.")
    return await assess_csv(file)

@app.get("/api/v1/transfers/recommendations", response_model=list[TransferCandidate])
async def transfer_recommendations():
    rows = load_rows(); groups = {}
    for row in rows: groups.setdefault(row["medicine_code"], []).append(row)
    recommendations = []
    for _, items in groups.items():
        donors = sorted([r for r in items if r["lead_time_days"] is not None and r["lead_time_days"] > 30], key=lambda r: -r["lead_time_days"])
        recipients = sorted([r for r in items if r["lead_time_days"] is not None and r["lead_time_days"] < 14], key=lambda r: r["lead_time_days"])
        for recipient, donor in zip(recipients, donors):
            if donor["facility"] == recipient["facility"]: continue
            units = max(0, int(min(donor["stock_units"] - donor["daily_consumption"]*30, recipient["daily_consumption"]*14-recipient["stock_units"])))
            if units:
                is_synthetic = bool(donor["is_synthetic"] or recipient["is_synthetic"])
                recommendations.append(TransferCandidate(donor_facility=donor["facility"],donor_district=donor["district"],recipient_facility=recipient["facility"],recipient_district=recipient["district"],medicine=recipient["medicine"],available_units=units,requested_units=units,donor_lead_time_days=donor["lead_time_days"],recipient_lead_time_days=recipient["lead_time_days"],data_source="synthetic" if is_synthetic else "real",is_synthetic=is_synthetic,provenance_status="synthetic" if is_synthetic else "uploaded_unverified"))
    return recommendations[:100]

@app.get("/api/v1/analytics/trust-metrics", response_model=TrustMetrics)
async def trust_metrics():
    metric = load_metrics()
    pairs = sorted(zip(metric.get("feature_names", []), metric.get("feature_importances", [])), key=lambda x: -x[1])[:12]
    return TrustMetrics(accuracy=metric.get("accuracy"),labels=metric.get("labels",[]),precision=metric.get("precision",[]),recall=metric.get("recall",[]),confusion_matrix=metric.get("confusion_matrix",[]),feature_importances=[{"feature":n,"importance":float(v)} for n,v in pairs],source=metric.get("source",""),provenance_status=metric["provenance_status"],verification=metric["verification"],model_validated=metric["model_validated"])
