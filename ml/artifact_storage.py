from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from backend.app.storage import (
    MAX_DASHBOARD_CSV_BYTES,
    ObjectStorageError,
    write_verified_object,
)

MAX_TRAINING_ARTIFACT_BYTES = 512 * 1024 * 1024


def store_file(
    key: str,
    path: Path,
    *,
    max_bytes: int = MAX_DASHBOARD_CSV_BYTES,
    backend: str | None = None,
) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Cannot persist missing file: {path}")
    if path.stat().st_size > max_bytes:
        raise ObjectStorageError("The file exceeds the configured storage size limit.")
    return write_verified_object(
        key,
        path.read_bytes(),
        max_bytes=max_bytes,
        backend=backend,
    )


def store_directory_archive(
    key: str,
    directory: Path,
    *,
    backend: str | None = None,
) -> str:
    if not directory.is_dir():
        raise FileNotFoundError(f"Cannot persist missing artifact directory: {directory}")

    root = directory.resolve()
    with tempfile.TemporaryDirectory(prefix="medipredict-storage-") as temporary:
        archive_path = Path(temporary) / "artifact.zip"
        with ZipFile(
            archive_path,
            "w",
            compression=ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for path in sorted(directory.rglob("*")):
                if path.is_symlink():
                    raise ValueError("Training artifacts cannot contain symbolic links.")
                if path.is_file():
                    resolved = path.resolve()
                    if root not in resolved.parents:
                        raise ValueError("Training artifact file is outside its directory.")
                    archive.write(path, path.relative_to(directory).as_posix())
        return store_file(
            key,
            archive_path,
            max_bytes=MAX_TRAINING_ARTIFACT_BYTES,
            backend=backend,
        )


def store_synthetic_dataset(
    directory: Path,
    *,
    backend: str | None = None,
) -> tuple[str, str]:
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    data_path = directory / "data.csv"
    if data_path.stat().st_size > MAX_DASHBOARD_CSV_BYTES:
        raise ObjectStorageError("The generated dataset exceeds the 20 MiB storage limit.")
    digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
    if (
        metadata.get("is_synthetic") is not True
        or metadata.get("data_source") != "synthetic_generated"
        or metadata.get("sha256") != digest
    ):
        raise ValueError("Generated dataset provenance or SHA-256 metadata is invalid.")

    prefix = f"datasets/synthetic_generated/{metadata['dataset_id']}"
    data_digest = store_file(
        f"{prefix}/data.csv",
        data_path,
        backend=backend,
    )
    metadata_digest = store_file(
        f"{prefix}/metadata.json",
        metadata_path,
        backend=backend,
    )
    return data_digest, metadata_digest


def store_feature_directory(
    directory: Path,
    *,
    backend: str | None = None,
) -> str:
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    build_id = metadata.get("build_id")
    if not isinstance(build_id, str) or not build_id:
        raise ValueError("Feature artifact is missing its build ID.")
    if not isinstance(metadata.get("is_synthetic"), bool):
        raise ValueError("Feature artifact is missing its synthetic-data flag.")
    return store_directory_archive(
        f"artifacts/features/{build_id}/feature-table.zip",
        directory,
        backend=backend,
    )


def store_model_directory(
    directory: Path,
    *,
    backend: str | None = None,
) -> str:
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    model_version = metadata.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        raise ValueError("Model artifact is missing its model version.")
    if not isinstance(metadata.get("is_synthetic"), bool):
        raise ValueError("Model artifact is missing its synthetic-data flag.")
    return store_directory_archive(
        f"artifacts/models/{model_version}/candidate.zip",
        directory,
        backend=backend,
    )
