"""Model loading, feature mapping, and stock risk inference."""
import hashlib
import json
import logging
import math
from functools import lru_cache
import re

import joblib
import pandas as pd
from .config import settings
from .provenance import ProvenanceError, resolve_provenance

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


def _model_artifact_hash_matches(metadata: dict) -> bool:
    hashes = metadata.get("artifact_sha256")
    expected_hash = hashes.get(settings.model_path.name) if isinstance(hashes, dict) else None
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        logger.warning(
            "Model artifact rejected: SHA-256 is missing or invalid for %s",
            settings.model_path.name,
        )
        return False

    digest = hashlib.sha256()
    try:
        with settings.model_path.open("rb") as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        logger.warning("Model artifact rejected: could not read artifact for hashing: %s", exc)
        return False

    if digest.hexdigest() != expected_hash:
        logger.warning(
            "Model artifact rejected: SHA-256 mismatch for %s",
            settings.model_path.name,
        )
        return False
    return True


def _resolve_model_provenance(metadata: dict) -> tuple[str, dict | None]:
    if metadata.get("is_synthetic") is True:
        return "synthetic", None
    data_hash = metadata.get("data_hash")
    verified_hash = metadata.get("verified_dataset_hash")
    if (
        metadata.get("provenance_status") != "verified"
        or not isinstance(data_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", data_hash)
        or verified_hash != data_hash
    ):
        return "uploaded_unverified", None
    dataset_id = metadata.get("source_dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id:
        logger.warning("Model provenance downgraded: source dataset ID is missing.")
        return "uploaded_unverified", None
    try:
        provenance = resolve_provenance(dataset_id, settings.uploads_path)
    except (FileNotFoundError, OSError, ProvenanceError) as exc:
        logger.warning("Model provenance downgraded: source registry could not be checked: %s", exc)
        return "uploaded_unverified", None
    verification = provenance.get("verification")
    if (
        provenance.get("provenance_status") != "verified"
        or not isinstance(verification, dict)
        or verification.get("dataset_sha256") != data_hash
    ):
        logger.warning(
            "Model provenance downgraded: current source dataset does not match model data hash."
        )
        return "uploaded_unverified", None
    return "verified", verification


@lru_cache(maxsize=1)
def get_model_bundle() -> tuple[object | None, dict | None]:
    if not settings.model_path.exists():
        logger.warning("Model artifact missing; using rule-based fallback")
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
    if metadata.get("model_validated") is not True:
        logger.warning("Model artifact rejected: model_validated is not true")
        return None, None
    if not _model_artifact_hash_matches(metadata):
        return None, None
    status, verification = _resolve_model_provenance(metadata)
    metadata["provenance_status"] = status
    metadata["verification"] = verification
    metadata["model_validated"] = bool(
        metadata.get("model_validated") is True and status == "verified"
    )
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
            "provenance_status": (
                "synthetic" if is_synthetic else "uploaded_unverified"
            ),
            "confidence_note": confidence_note,
        })
    return assessed

def load_metrics() -> dict:
    provenance_status = "uploaded_unverified"
    verification = None
    model_validated = False
    try:
        metadata = json.loads(settings.metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    if isinstance(metadata, dict):
        provenance_status, verification = _resolve_model_provenance(metadata)
        model_validated = bool(
            metadata.get("model_validated") is True
            and provenance_status == "verified"
            and settings.model_path.is_file()
            and _model_artifact_hash_matches(metadata)
        )
    return {
        "accuracy": None,
        "labels": [],
        "precision": [],
        "recall": [],
        "confusion_matrix": [],
        "feature_names": [],
        "feature_importances": [],
        "source": "No validated model metrics are available.",
        "provenance_status": provenance_status,
        "verification": verification,
        "model_validated": model_validated,
    }
