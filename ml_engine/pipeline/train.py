"""Train and evaluate the MediPredict stock risk classifier."""
# Legacy metrics from this trainer are invalid evidence: the split is random and
# the same-row target is derived from stock/consumption features (label leakage).
import os
from pathlib import Path
import json
import pandas as pd
import joblib
from dotenv import load_dotenv
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[1]


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (ROOT / path).resolve()


load_dotenv(ROOT / ".env")
configured_data_path = os.getenv("ML_ENGINE_TRAINING_DATA_PATH")
DATA_CANDIDATES = (
    [resolve_path(configured_data_path)]
    if configured_data_path
    else [
        ROOT / "datasets/processed/medipredict_facility_timeseries_2026.csv",
        ROOT.parent / "datasets/medipredict_data/processed/medipredict_facility_timeseries_2026.csv",
    ]
)
OUT = resolve_path(os.getenv("ML_ENGINE_ARTIFACTS_DIR", "models_store"))
NUMERIC = ["end_of_month_stock_units", "avg_daily_consumption_units", "nisr_under_5_population", "nisr_poverty_rate_pct", "nisr_malaria_prevalence_pct", "rainy_season_active"]
CATEGORICAL = ["medicine_code", "district", "facility_type"]
TARGET = "stockout_risk_label"

def main():
    if os.getenv("MEDIPREDICT_ENABLE_LEGACY_TRAINER", "").strip().casefold() != "true":
        raise SystemExit(
            "Deprecated trainer disabled. Its random split and same-row label leakage "
            "make its metrics invalid. Use `python -m ml.train <feature-build-id>`."
        )
    source = next((p for p in DATA_CANDIDATES if p.exists()), None)
    if source is None:
        raise FileNotFoundError(
            "Facility time-series CSV not found. Set ML_ENGINE_TRAINING_DATA_PATH "
            "or provide the CSV in ml_engine/datasets or datasets/medipredict_data/processed."
        )
    data = pd.read_csv(source).dropna(subset=NUMERIC + CATEGORICAL + [TARGET])
    x = data[NUMERIC + CATEGORICAL]
    y = data[TARGET].str.upper()
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=.2, random_state=42, stratify=y)
    prep = ColumnTransformer([("numeric", "passthrough", NUMERIC), ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL)])
    model = Pipeline([("features", prep), ("classifier", RandomForestClassifier(n_estimators=350, min_samples_leaf=2, class_weight="balanced", random_state=42, n_jobs=-1))])
    model.fit(x_train, y_train)
    predicted = model.predict(x_test)
    labels = ["CRITICAL", "MODERATE", "STABLE"]
    precision, recall, _, _ = precision_recall_fscore_support(y_test, predicted, labels=labels, zero_division=0)
    OUT.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, OUT / "medipredict_rf_model.pkl")
    joblib.dump(model.named_steps["features"], OUT / "medipredict_encoders.pkl")
    metrics = {"accuracy": accuracy_score(y_test, predicted), "labels": labels, "precision": precision.tolist(), "recall": recall.tolist(), "confusion_matrix": confusion_matrix(y_test, predicted, labels=labels).tolist(), "feature_names": model.named_steps["features"].get_feature_names_out().tolist(), "feature_importances": model.named_steps["classifier"].feature_importances_.tolist(), "rows": len(data), "source": str(source)}
    (OUT / "medipredict_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Trained on {len(data):,} rows; holdout accuracy {metrics['accuracy']:.3f}; artifacts in {OUT}")

if __name__ == "__main__":
    main()
