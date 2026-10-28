"""Model loading, feature mapping, and stock risk inference."""
import json
import logging
import math
from functools import lru_cache

import joblib
import pandas as pd
from .config import settings

logger = logging.getLogger(__name__)
REQUIRED_MODEL_METADATA = (
    "time_based_split",
    "test_metrics",
    "training_date_range",
    "data_hash",
    "feature_list",
    "horizon_days",
    "is_synthetic",
)


@lru_cache(maxsize=1)
def get_model_bundle() -> tuple[object | None, dict | None]:
    if not settings.model_path.exists():
        return None, None

    metadata: dict = {}
    try:
        metadata = json.loads(settings.metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Model artifact rejected: metadata could not be read: %s", exc)

    missing = [field for field in REQUIRED_MODEL_METADATA if field not in metadata]
    if missing:
        logger.warning(
            "Model artifact rejected; missing required metadata fields: %s",
            ", ".join(missing),
        )
        return None, None

    test_metrics = metadata["test_metrics"]
    invalid = []
    if metadata["time_based_split"] is not True:
        invalid.append("time_based_split")
    if not isinstance(test_metrics, dict) or not all(
        isinstance(test_metrics.get(name), (int, float))
        for name in ("pr_auc", "roc_auc")
    ):
        invalid.append("test_metrics.pr_auc/test_metrics.roc_auc")
    if not isinstance(metadata["training_date_range"], (str, dict)) or not metadata["training_date_range"]:
        invalid.append("training_date_range")
    if not isinstance(metadata["data_hash"], str) or not metadata["data_hash"]:
        invalid.append("data_hash")
    if not isinstance(metadata["feature_list"], list) or not metadata["feature_list"]:
        invalid.append("feature_list")
    if not isinstance(metadata["horizon_days"], int) or metadata["horizon_days"] <= 0:
        invalid.append("horizon_days")
    if not isinstance(metadata["is_synthetic"], bool):
        invalid.append("is_synthetic")
    if invalid:
        logger.warning(
            "Model artifact rejected; invalid metadata fields: %s",
            ", ".join(invalid),
        )
        return None, None
    if metadata["is_synthetic"]:
        logger.warning(
            "Model artifact rejected; is_synthetic=true does not validate real-world performance"
        )
        return None, None

    try:
        return joblib.load(settings.model_path), metadata
    except Exception:
        logger.exception("Model artifact could not be loaded; using rule-based fallback")
        return None, None


def get_model():
    return get_model_bundle()[0]

def risk_from_lead_time(days: float | None) -> str:
    if days is None or not math.isfinite(days):
        return "UNKNOWN"
    if days < 7: return "CRITICAL"
    if days <= 14: return "MODERATE"
    return "STABLE"


def estimate_stock_after_days(
    stock_units: object,
    daily_consumption: object,
    days: int,
) -> float | None:
    """Project remaining stock at a constant reported consumption rate, without receipts."""
    try:
        stock = float(stock_units)
        consumption = float(daily_consumption)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(stock) or stock < 0 or days < 0:
        return None
    if stock == 0:
        return 0.0
    if not math.isfinite(consumption) or consumption <= 0:
        return None
    return round(max(0.0, stock - consumption * days), 1)


def parse_is_synthetic(value: object) -> bool:
    normalized = str(value).strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("accepted values are true or false (case-insensitive)")


def infer(records: list[dict], data_source: str | None = None) -> list[dict]:
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
    lead_times = [
        (
            float(row["end_of_month_stock_units"])
            / float(row["avg_daily_consumption_units"])
            if (
                math.isfinite(float(row["end_of_month_stock_units"]))
                and math.isfinite(float(row["avg_daily_consumption_units"]))
                and float(row["avg_daily_consumption_units"]) > 0
            )
            else None
        )
        for _, row in features.iterrows()
    ]
    labels = [
        (
            "CRITICAL"
            if stock <= 0
            or str(record.get("stockout_flag", "")).strip().casefold() == "true"
            or float(record.get("stock_out_days", 0) or 0) > 0
            else risk_from_lead_time(days)
        )
        for record, stock, days in zip(
            records, features["end_of_month_stock_units"], lead_times
        )
    ]
    confidence = [None for _ in labels]
    method = "rule_based_fallback"
    model_version = None
    model_validated = False
    confidence_note = (
        "Stock-cover estimate uses reported stock and average daily consumption. "
        "Assumes constant consumption and no incoming receipts; not a probability."
    )

    assessed = []
    for i, record in enumerate(records):
        is_synthetic = parse_is_synthetic(record["is_synthetic"])
        source = data_source or ("synthetic" if is_synthetic else "real")
        assessed.append({
            **record,
            "lead_time_days": round(lead_times[i], 1) if lead_times[i] is not None else None,
            "estimated_stock_after_7_days": estimate_stock_after_days(
                features.iloc[i]["end_of_month_stock_units"],
                features.iloc[i]["avg_daily_consumption_units"],
                7,
            ),
            "estimated_stock_after_14_days": estimate_stock_after_days(
                features.iloc[i]["end_of_month_stock_units"],
                features.iloc[i]["avg_daily_consumption_units"],
                14,
            ),
            "risk_level": str(labels[i]),
            "confidence": confidence[i],
            "method": method,
            "model_version": model_version,
            "model_validated": model_validated,
            "data_source": source,
            "is_synthetic": is_synthetic,
            "confidence_note": confidence_note,
        })
    return assessed

def load_metrics() -> dict:
    return {
        "accuracy": None,
        "labels": [],
        "precision": [],
        "recall": [],
        "confusion_matrix": [],
        "feature_names": [],
        "feature_importances": [],
        "source": "No validated model metrics are available.",
    }
