from contextlib import asynccontextmanager
from pathlib import Path
import io
import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .database import Base, engine, get_db
from . import models
from .ml_service import infer, load_metrics
from .schemas.api import Summary, RiskRecord, UploadResult, TransferCandidate, TrustMetrics

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
    df = df.sort_values("reporting_month").groupby(["facility_name", "medicine_code"], as_index=False).tail(1)
    df = df.rename(columns=CSV_COLUMNS)
    rows = df.to_dict(orient="records")
    return infer(rows)

@app.get("/api/v1/health")
async def health(): return {"status": "ok", "service": settings.app_name}

@app.get("/api/v1/inventory/summary", response_model=Summary)
async def inventory_summary(db: Session = Depends(get_db)):
    rows = load_rows()
    if not rows: return Summary(facilities=0,districts=0,medicines=0,critical=0,moderate=0,stable=0,stock_units=0,reporting_date="—")
    return Summary(facilities=len({r["facility"] for r in rows}), districts=len({r["district"] for r in rows}), medicines=len({r["medicine_code"] for r in rows}), critical=sum(r["risk_level"]=="CRITICAL" for r in rows), moderate=sum(r["risk_level"]=="MODERATE" for r in rows), stable=sum(r["risk_level"]=="STABLE" for r in rows), stock_units=int(sum(r["stock_units"] for r in rows)), reporting_date=str(max(r["reporting_date"] for r in rows)))

@app.get("/api/v1/predictions/risk-register", response_model=list[RiskRecord])
async def risk_register(risk: str | None = Query(default=None), district: str | None = Query(default=None), search: str | None = Query(default=None), limit: int = Query(default=500, ge=1, le=5000)):
    rows = load_rows()
    if risk: rows = [r for r in rows if r["risk_level"] == risk.upper()]
    if district: rows = [r for r in rows if r["district"].casefold() == district.casefold()]
    if search: rows = [r for r in rows if search.casefold() in (r["facility"]+r["medicine"]+r["district"]).casefold()]
    return sorted(rows, key=lambda r: (0 if r["risk_level"]=="CRITICAL" else 1 if r["risk_level"]=="MODERATE" else 2, r["lead_time_days"]))[:limit]

@app.post("/api/v1/data/upload-csv", response_model=UploadResult)
async def upload_csv(file: UploadFile = File(...)):
    if not file.filename or Path(file.filename).suffix.casefold() != ".csv": raise HTTPException(400, "Upload a .csv file")
    try:
        content = await file.read()
        if len(content) > 20 * 1024 * 1024: raise HTTPException(413, "CSV must be smaller than 20 MB")
        frame = pd.read_csv(io.BytesIO(content))
        missing = [key for key in CSV_COLUMNS if key not in frame.columns]
        if missing: raise HTTPException(422, f"Missing required columns: {', '.join(missing)}")
        rows = frame.rename(columns=CSV_COLUMNS).to_dict(orient="records")
        rows = infer(rows)
        return UploadResult(records_received=len(rows), predictions=len(rows), critical=sum(x["risk_level"]=="CRITICAL" for x in rows), moderate=sum(x["risk_level"]=="MODERATE" for x in rows), stable=sum(x["risk_level"]=="STABLE" for x in rows), items=rows[:500])
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422, f"Could not parse CSV: {exc}") from exc

@app.get("/api/v1/transfers/recommendations", response_model=list[TransferCandidate])
async def transfer_recommendations():
    rows = load_rows(); groups = {}
    for row in rows: groups.setdefault(row["medicine_code"], []).append(row)
    recommendations = []
    for _, items in groups.items():
        donors = sorted([r for r in items if r["lead_time_days"] > 30], key=lambda r: -r["lead_time_days"])
        recipients = sorted([r for r in items if r["lead_time_days"] < 14], key=lambda r: r["lead_time_days"])
        for recipient, donor in zip(recipients, donors):
            if donor["facility"] == recipient["facility"]: continue
            units = max(0, int(min(donor["stock_units"] - donor["daily_consumption"]*30, recipient["daily_consumption"]*14-recipient["stock_units"])))
            if units: recommendations.append(TransferCandidate(donor_facility=donor["facility"],donor_district=donor["district"],recipient_facility=recipient["facility"],recipient_district=recipient["district"],medicine=recipient["medicine"],available_units=units,requested_units=units,donor_lead_time_days=donor["lead_time_days"],recipient_lead_time_days=recipient["lead_time_days"]))
    return recommendations[:100]

@app.get("/api/v1/analytics/trust-metrics", response_model=TrustMetrics)
async def trust_metrics():
    metric = load_metrics()
    pairs = sorted(zip(metric.get("feature_names", []), metric.get("feature_importances", [])), key=lambda x: -x[1])[:12]
    return TrustMetrics(accuracy=metric.get("accuracy",0),labels=metric.get("labels",[]),precision=metric.get("precision",[]),recall=metric.get("recall",[]),confusion_matrix=metric.get("confusion_matrix",[]),feature_importances=[{"feature":n,"importance":float(v)} for n,v in pairs],source=metric.get("source",""))
