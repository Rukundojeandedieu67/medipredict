from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.config import settings
from .build_dataset import (
    DEFAULT_OUTPUT_ROOT as DEFAULT_FEATURE_ROOT,
    _load_registered_dataset,
    build_dataset,
)
from .train import MODEL_ROOT, train_feature_dataset


def train_uploaded_candidate(
    dataset_id: str,
    *,
    uploads_root: Path = settings.uploads_path,
    feature_root: Path = DEFAULT_FEATURE_ROOT,
    model_root: Path = MODEL_ROOT,
    minimum_history_periods: int = 24,
    bootstrap_repetitions: int = 1000,
) -> Path:
    _, registry, _ = _load_registered_dataset(dataset_id, uploads_root)
    if registry.get("data_source") != "uploaded":
        raise ValueError("Real-data training requires a dataset registered by training-upload.")
    if registry.get("is_synthetic") is not False:
        raise ValueError(
            "Real-data training requires is_synthetic=false in the registered upload."
        )

    feature_directory = build_dataset(
        dataset_id,
        uploads_root=uploads_root,
        output_root=feature_root,
    )
    feature_metadata = json.loads(
        (feature_directory / "metadata.json").read_text(encoding="utf-8")
    )
    return train_feature_dataset(
        feature_metadata["build_id"],
        feature_root=feature_root,
        model_root=model_root,
        minimum_history_periods=minimum_history_periods,
        bootstrap_repetitions=bootstrap_repetitions,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build and train a candidate from a real, non-synthetic dataset "
            "previously accepted by the protected training-upload endpoint."
        )
    )
    parser.add_argument("dataset_id", help="Dataset ID returned by training-upload.")
    parser.add_argument("--uploads-root", type=Path, default=settings.uploads_path)
    parser.add_argument("--feature-root", type=Path, default=DEFAULT_FEATURE_ROOT)
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--minimum-history-periods", type=int, default=24)
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    args = parser.parse_args()
    artifact = train_uploaded_candidate(
        args.dataset_id,
        uploads_root=args.uploads_root,
        feature_root=args.feature_root,
        model_root=args.model_root,
        minimum_history_periods=args.minimum_history_periods,
        bootstrap_repetitions=args.bootstrap_repetitions,
    )
    metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
    print(
        f"Candidate artifact: {artifact} "
        f"(model_validated={metadata['model_validated']}, "
        f"provenance_status={metadata['provenance_status']})"
    )


if __name__ == "__main__":
    main()
