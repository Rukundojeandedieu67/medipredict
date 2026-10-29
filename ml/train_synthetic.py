from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from backend.app.config import settings
from .artifact_storage import (
    store_feature_directory,
    store_model_directory,
    store_synthetic_dataset,
)
from .build_dataset import build_dataset
from .synthetic import generate_synthetic_supply_history
from .train import FEATURE_ROOT, MODEL_ROOT, train_feature_dataset

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DATA_ROOT = ROOT / "ml" / "artifacts" / "synthetic_datasets"
SYNTHETIC_NOTICE = "SYNTHETIC - not evidence of real-world performance"


def prepare_synthetic_feature_dataset(
    *,
    data_root: Path = SYNTHETIC_DATA_ROOT,
    feature_root: Path = FEATURE_ROOT,
    facilities: int = 48,
    periods: int = 72,
    seed: int = 17,
) -> Path:
    source = generate_synthetic_supply_history(
        facilities=facilities,
        periods=periods,
        seed=seed,
        frequency="monthly",
    )
    dataset_id = (
        "v1-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex
    )
    dataset_dir = data_root / "v1" / dataset_id
    dataset_dir.mkdir(parents=True, exist_ok=False)
    data_path = dataset_dir / "data.csv"
    source.to_csv(data_path, index=False)
    registry = {
        "dataset_id": dataset_id,
        "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "row_count": len(source),
        "date_range": {
            "start": source["date"].min(),
            "end": source["date"].max(),
        },
        "is_synthetic": True,
        "data_source": "synthetic_generated",
        "data_frequency": "monthly",
    }
    (dataset_dir / "metadata.json").write_text(
        json.dumps(registry, indent=2), encoding="utf-8"
    )
    store_synthetic_dataset(dataset_dir, backend=settings.storage_backend)
    feature_directory = build_dataset(
        dataset_id,
        frequency="monthly",
        horizon=1,
        minimum_records_per_facility_item=24,
        minimum_facility_items=1,
        minimum_positives=1,
        uploads_root=data_root,
        output_root=feature_root,
    )
    store_feature_directory(feature_directory, backend=settings.storage_backend)
    return feature_directory


def train_synthetic_candidate(
    *,
    data_root: Path = SYNTHETIC_DATA_ROOT,
    feature_root: Path = FEATURE_ROOT,
    model_root: Path = MODEL_ROOT,
    facilities: int = 48,
    periods: int = 72,
    seed: int = 17,
    bootstrap_repetitions: int = 1000,
) -> Path:
    feature_dir = prepare_synthetic_feature_dataset(
        data_root=data_root,
        feature_root=feature_root,
        facilities=facilities,
        periods=periods,
        seed=seed,
    )
    feature_metadata = json.loads(
        (feature_dir / "metadata.json").read_text(encoding="utf-8")
    )
    model_directory = train_feature_dataset(
        feature_metadata["build_id"],
        feature_root=feature_root,
        model_root=model_root,
        bootstrap_repetitions=bootstrap_repetitions,
    )
    store_model_directory(model_directory, backend=settings.storage_backend)
    return model_directory


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Train a synthetic-only candidate through the production feature and "
            "evaluation pipeline."
        )
    )
    parser.add_argument("--data-root", type=Path, default=SYNTHETIC_DATA_ROOT)
    parser.add_argument("--feature-root", type=Path, default=FEATURE_ROOT)
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--facilities", type=int, default=48)
    parser.add_argument("--periods", type=int, default=72)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    args = parser.parse_args()
    artifact = train_synthetic_candidate(
        data_root=args.data_root,
        feature_root=args.feature_root,
        model_root=args.model_root,
        facilities=args.facilities,
        periods=args.periods,
        seed=args.seed,
        bootstrap_repetitions=args.bootstrap_repetitions,
    )
    print(f"{SYNTHETIC_NOTICE} | Candidate artifact: {artifact}")


if __name__ == "__main__":
    main()
