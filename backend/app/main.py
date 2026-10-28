from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
from pathlib import Path
import io
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
    Base.metadata.create_all(bind=engine)
    yield
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def load_rows() -> list[dict]:
    if not settings.csv_path.exists(): return []
    df = pd.read_csv(settings.csv_path)
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
        content = await file.read()
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


@app.post("/api/v1/data/training-upload", response_model=TrainingUploadResult)
async def training_upload(
    file: UploadFile = File(...),
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    x_uploader: str | None = Header(default=None, alias="X-Uploader"),
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
    dataset_dir = settings.uploads_path / "v1" / dataset_id
    dataset_dir.mkdir(parents=True, exist_ok=False)
    data_path = dataset_dir / "data.csv"
    metadata_path = dataset_dir / "metadata.json"
    digest = hashlib.sha256(content).hexdigest()
    synthetic = report.is_synthetic
    metadata = {
        "dataset_id": dataset_id,
        "sha256": digest,
        "uploader": (x_uploader or "admin").strip()[:160],
        "uploader_identity": (x_uploader or "").strip()[:160] or None,
        "uploaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "row_count": report.row_count,
        "date_range": report.date_range,
        "data_frequency": report.data_frequency,
        "is_synthetic": synthetic,
        "data_source": "uploaded",
    }
    with data_path.open("xb") as destination:
        destination.write(content)
    with metadata_path.open("x", encoding="utf-8") as destination:
        json.dump(metadata, destination, indent=2)

    return TrainingUploadResult(
        dataset_id=dataset_id,
        sha256=digest,
        row_count=report.row_count,
        date_range=report.date_range,
        data_frequency=report.data_frequency,
        is_synthetic=synthetic,
        data_source="uploaded",
        metadata_path=metadata_path.relative_to(settings.uploads_path).as_posix(),
        provenance_status=resolve_provenance(
            dataset_id, settings.uploads_path
        )["provenance_status"],
        verification_summary=None,
    )


def _dataset_response(dataset_id: str) -> DatasetDetail:
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
):
    _require_admin(x_admin_api_key, operation="Dataset listing")
    root = settings.uploads_path / "v1"
    if not root.exists():
        return []
    return [
        _dataset_response(directory.name)
        for directory in sorted(root.iterdir())
        if directory.is_dir()
    ]


@app.get("/api/v1/data/datasets/{dataset_id}/provenance", response_model=ProvenanceResponse)
async def dataset_provenance(
    dataset_id: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
):
    _require_admin(x_admin_api_key, operation="Dataset provenance")
    try:
        return resolve_provenance(dataset_id, settings.uploads_path)
    except (FileNotFoundError, ProvenanceError) as exc:
        raise _provenance_http_error(exc) from exc


@app.get("/api/v1/data/datasets/{dataset_id}", response_model=DatasetDetail)
async def dataset_detail(
    dataset_id: str,
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
):
    _require_admin(x_admin_api_key, operation="Dataset detail")
    return _dataset_response(dataset_id)


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
):
    _require_admin(x_admin_api_key, operation="Dataset verification")
    evidence: bytes | None = None
    if evidence_file is not None:
        evidence = await evidence_file.read(MAX_CSV_BYTES + 1)
        if len(evidence) > MAX_CSV_BYTES:
            raise HTTPException(413, "Evidence file must be smaller than 20 MB.")
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
):
    _require_admin(x_admin_api_key, operation="Verification revocation")
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
