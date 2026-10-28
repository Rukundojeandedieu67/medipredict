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
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
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
    TrustMetrics,
)
from .validation import ValidationConfig, validate_inventory_csv

logger = logging.getLogger(__name__)
MAX_CSV_BYTES = 20 * 1024 * 1024
CSV_COLUMNS = {"facility_name": "facility", "district": "district", "province": "province", "facility_type": "facility_type", "medicine_code": "medicine_code", "medicine_name": "medicine", "end_of_month_stock_units": "stock_units", "avg_daily_consumption_units": "daily_consumption", "nisr_under_5_population": "under5_population", "nisr_poverty_rate_pct": "poverty_rate", "nisr_malaria_prevalence_pct": "malaria_prevalence", "rainy_season_active": "rainy_season", "reporting_month": "reporting_date"}
@asynccontextmanager
async def lifespan(app: FastAPI):
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=engine)
    yield
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def load_rows() -> list[dict]:
    try:
        content = read_dashboard_csv()
    except (ObjectStorageError, StorageConfigurationError) as exc:
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
async def inventory_summary(db: Session = Depends(get_db)):
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
        synthetic = parse_is_synthetic(row["is_synthetic"])
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


@app.post("/api/v1/data/assess-csv", response_model=CsvAssessmentResult)
async def assess_csv(file: UploadFile = File(...)):
    _, frame = await _read_csv(file)
    report = _validation_report(frame, "assessment")
    if report.data_frequency == "monthly":
        raise HTTPException(
            status_code=422,
            detail=(
                "Rule-based CSV assessment currently supports daily-frequency data only. "
                "Monthly data can be validated and prepared for feature analysis."
            ),
        )
    return _assessment_result(frame, report)


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
    try:
        write_object(object_key, content)
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
        db.commit()
    except (ObjectStorageError, StorageConfigurationError) as exc:
        db.rollback()
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
    )


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
