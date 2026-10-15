"""Model loading, feature mapping, and stock risk inference."""
import json
from functools import lru_cache
import joblib
import pandas as pd
from .config import settings

@lru_cache(maxsize=1)
def get_model():
    if settings.model_path.exists(): return joblib.load(settings.model_path)
    return None

def risk_from_lead_time(days: float) -> str:
    if days < 7: return "CRITICAL"
    if days <= 14: return "MODERATE"
    return "STABLE"

def infer(records: list[dict]) -> list[dict]:
    model = get_model()
    features = pd.DataFrame([{
        "end_of_month_stock_units": float(r.get("stock_units", r.get("end_of_month_stock_units", 0))),
        "avg_daily_consumption_units": float(r.get("daily_consumption", r.get("avg_daily_consumption_units", 0))),
        "nisr_under_5_population": int(r.get("under5_population", r.get("nisr_under_5_population", 0))),
        "nisr_poverty_rate_pct": float(r.get("poverty_rate", r.get("nisr_poverty_rate_pct", 0))),
        "nisr_malaria_prevalence_pct": float(r.get("malaria_prevalence", r.get("nisr_malaria_prevalence_pct", 0))),
        "rainy_season_active": int(r.get("rainy_season", r.get("rainy_season_active", 0))),
        "medicine_code": r.get("medicine_code", "UNKNOWN"), "district": r.get("district", "Unknown"),
        "facility_type": r.get("facility_type", "Health Center")
    } for r in records])
    lead_times = [float(row["end_of_month_stock_units"]) / max(float(row["avg_daily_consumption_units"]), 0.01) for _, row in features.iterrows()]
    if model is not None:
        probabilities = model.predict_proba(features)
        classes = list(model.classes_)
        labels = model.predict(features)
        confidence = [float(probabilities[i][classes.index(labels[i])]) for i in range(len(labels))]
    else:
        labels = [risk_from_lead_time(days) for days in lead_times]
        confidence = [0.75 for _ in labels]
    return [{**r, "lead_time_days": round(lead_times[i], 1), "risk_level": str(labels[i]), "confidence": round(confidence[i], 3)} for i, r in enumerate(records)]

def load_metrics() -> dict:
    if settings.metrics_path.exists():
        return json.loads(settings.metrics_path.read_text(encoding="utf-8"))
    return {"accuracy": 0, "labels": ["CRITICAL", "MODERATE", "STABLE"], "precision": [0,0,0], "recall": [0,0,0], "confusion_matrix": [[0,0,0],[0,0,0],[0,0,0]], "feature_names": [], "feature_importances": [], "source": "Model artifacts are not trained yet"}
