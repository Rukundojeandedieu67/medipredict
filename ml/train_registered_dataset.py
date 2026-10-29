from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.main import _dataset_workspace
from backend.app.storage import ObjectStorageError, read_object, write_object
from .build_dataset import build_dataset
from .train import train_feature_dataset

MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_directory(source: Path, destination: Path) -> None:
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


def _store_verified_artifact(
    key: str,
    archive_path: Path,
    *,
    backend: str | None = None,
) -> str:
    content = archive_path.read_bytes()
    if len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError(f"Training artifact exceeds the {MAX_ARTIFACT_BYTES}-byte limit.")
    digest = _sha256(content)
    try:
        write_object(key, content, backend=backend)
    except ObjectStorageError as write_error:
        try:
            existing = read_object(
                key,
                max_bytes=MAX_ARTIFACT_BYTES,
                backend=backend,
            )
        except ObjectStorageError as read_error:
            raise ObjectStorageError(
                f"Could not store or verify immutable training artifact {key}."
            ) from read_error
        if _sha256(existing) != digest:
            raise ObjectStorageError(
                f"An artifact object already exists with different content: {key}."
            ) from write_error
        return digest
    stored = read_object(
        key,
        max_bytes=MAX_ARTIFACT_BYTES,
        backend=backend,
    )
    if _sha256(stored) != digest:
        raise ObjectStorageError(f"Stored training artifact failed SHA-256 verification: {key}.")
    return digest


def train_registered_dataset(
    dataset_id: str,
    db: Session,
    *,
    minimum_history_periods: int = 24,
    bootstrap_repetitions: int = 1000,
) -> models.ModelRelease:
    if not settings.database_enabled:
        raise RuntimeError("Enable MEDIPREDICT_DATABASE_ENABLED to run a training job.")
    if minimum_history_periods < 1:
        raise ValueError("minimum_history_periods must be positive.")
    if bootstrap_repetitions < 1000:
        raise ValueError("At least 1000 bootstrap repetitions are required.")

    source_record = db.get(models.DatasetRecord, dataset_id)
    if source_record is None:
        raise ValueError(f"Registered dataset not found: {dataset_id}")

    with tempfile.TemporaryDirectory(prefix="medipredict-training-") as temporary:
        workspace = Path(temporary)
        with _dataset_workspace(source_record, db) as uploads_root:
            feature_root = workspace / "feature_tables"
            feature_directory = build_dataset(
                dataset_id,
                uploads_root=uploads_root,
                output_root=feature_root,
            )
        feature_build_id = feature_directory.name
        model_root = workspace / "models"
        model_directory = train_feature_dataset(
            feature_build_id,
            feature_root=feature_root,
            model_root=model_root,
            minimum_history_periods=minimum_history_periods,
            bootstrap_repetitions=bootstrap_repetitions,
        )

        feature_metadata = json.loads(
            (feature_directory / "metadata.json").read_text(encoding="utf-8")
        )
        model_metadata = json.loads(
            (model_directory / "metadata.json").read_text(encoding="utf-8")
        )
        if model_metadata.get("source_dataset_id") != dataset_id:
            raise ValueError("Model metadata does not reference the requested source dataset.")
        if model_metadata.get("data_hash") != source_record.sha256:
            raise ValueError("Model metadata dataset hash does not match the Aiven registry.")
        is_synthetic = model_metadata.get("is_synthetic")
        model_validated = model_metadata.get("model_validated")
        if not isinstance(is_synthetic, bool) or not isinstance(model_validated, bool):
            raise ValueError("Model metadata is missing valid provenance or validation flags.")
        if (
            source_record.is_synthetic is not None
            and source_record.is_synthetic != is_synthetic
        ):
            raise ValueError("Model provenance does not match the registered source dataset.")

        feature_key = f"artifacts/features/{feature_build_id}/feature-table.zip"
        model_version = str(model_metadata["model_version"])
        model_key = f"artifacts/models/{model_version}/candidate.zip"
        feature_zip = workspace / "feature-table.zip"
        model_zip = workspace / "candidate.zip"
        _zip_directory(feature_directory, feature_zip)
        _zip_directory(model_directory, model_zip)

        feature_bundle_sha256 = _store_verified_artifact(
            feature_key, feature_zip, backend=source_record.storage_backend
        )
        model_bundle_sha256 = _store_verified_artifact(
            model_key, model_zip, backend=source_record.storage_backend
        )
        artifact_hashes = model_metadata.get("artifact_sha256")
        if not isinstance(artifact_hashes, dict):
            raise ValueError("Model metadata is missing its artifact hashes.")
        model_sha256 = artifact_hashes.get("model.joblib")
        if not isinstance(model_sha256, str) or len(model_sha256) != 64:
            raise ValueError("Model metadata has no valid model.joblib SHA-256.")

        stored_metadata = {
            **model_metadata,
            "release_status": "candidate",
            "model_bundle_key": model_key,
            "model_bundle_sha256": model_bundle_sha256,
            "feature_bundle_key": feature_key,
            "feature_bundle_sha256": feature_bundle_sha256,
            "feature_dataset_id": feature_build_id,
            "feature_table_sha256": feature_metadata["feature_table_sha256"],
            "training_policy": "manual_review_required",
            "storage_backend": source_record.storage_backend,
        }
        release = models.ModelRelease(
            model_version=model_version,
            source_dataset_id=dataset_id,
            source_dataset_sha256=source_record.sha256,
            artifact_key=model_key,
            model_sha256=model_sha256,
            metadata_json=stored_metadata,
            is_synthetic=is_synthetic,
            model_validated=model_validated,
            release_status="candidate",
        )
        try:
            db.add(release)
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise
        return release


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Manually train and store a candidate from a validated dataset registered "
            "in configured storage. This does not promote or serve the model."
        )
    )
    parser.add_argument("dataset_id", help="Dataset ID returned by the training-upload endpoint.")
    parser.add_argument("--minimum-history-periods", type=int, default=24)
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    args = parser.parse_args()
    with SessionLocal() as session:
        release = train_registered_dataset(
            args.dataset_id,
            session,
            minimum_history_periods=args.minimum_history_periods,
            bootstrap_repetitions=args.bootstrap_repetitions,
        )
    synthetic_notice = " SYNTHETIC - not evidence of real-world performance." if release.is_synthetic else ""
    print(
        f"Candidate stored: {release.model_version}; "
        f"validated={release.model_validated}; "
        f"status={release.release_status}; "
        f"R2 key={release.artifact_key}.{synthetic_notice}"
    )


if __name__ == "__main__":
    main()
