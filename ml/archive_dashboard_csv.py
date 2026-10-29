from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.storage import (
    ObjectStorageError,
    StorageConfigurationError,
    read_object,
    write_object,
)

REQUIRED_COLUMNS = {
    "reporting_month",
    "facility_name",
    "medicine_code",
    "end_of_month_stock_units",
    "avg_daily_consumption_units",
    "is_synthetic",
}
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024


def _write_immutable_object(key: str, content: bytes) -> None:
    try:
        write_object(key, content, backend="s3")
    except ObjectStorageError as write_error:
        try:
            existing = read_object(
                key,
                max_bytes=MAX_ARCHIVE_BYTES,
                backend="s3",
            )
        except (ObjectStorageError, StorageConfigurationError) as read_error:
            raise ObjectStorageError(
                f"Could not store or verify immutable archive object {key}."
            ) from read_error
        if hashlib.sha256(existing).digest() != hashlib.sha256(content).digest():
            raise ObjectStorageError(
                f"An archive object already exists with different content: {key}."
            ) from write_error


def archive_dashboard_csv(
    db: Session,
    *,
    source_path: Path | None = None,
) -> models.DatasetArchive:
    if not settings.database_enabled:
        raise RuntimeError("Enable MEDIPREDICT_DATABASE_ENABLED to register the archive.")
    if settings.storage_backend != "s3":
        raise RuntimeError(
            "Set MEDIPREDICT_STORAGE_BACKEND=s3 to archive the CSV to Cloudflare R2."
        )

    csv_path = source_path or settings.csv_path
    content = csv_path.read_bytes()
    if len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError("Dashboard CSV exceeds the 20 MiB archive size limit.")
    frame = pd.read_csv(
        io.BytesIO(content),
        dtype=str,
        keep_default_na=False,
    )
    missing_columns = sorted(REQUIRED_COLUMNS.difference(frame.columns))
    if missing_columns:
        raise ValueError(
            "Dashboard CSV is missing required archive columns: "
            + ", ".join(missing_columns)
        )
    if frame.empty:
        raise ValueError("Dashboard CSV contains no records.")
    synthetic_flags = frame["is_synthetic"].str.strip().str.casefold()
    if not synthetic_flags.eq("true").all():
        raise ValueError(
            "This archive command only accepts the current all-synthetic dashboard CSV."
        )
    periods = pd.to_datetime(
        frame["reporting_month"],
        format="%Y-%m",
        errors="coerce",
    )
    if periods.isna().any():
        raise ValueError("Dashboard CSV contains an invalid reporting_month value.")

    digest = hashlib.sha256(content).hexdigest()
    archive_id = f"dashboard-{digest}"
    object_key = f"archives/dashboard/{digest}/medipredict_facility_timeseries_2026.csv"
    manifest_key = f"{object_key}.metadata.json"
    metadata = {
        "archive_id": archive_id,
        "source_name": csv_path.name,
        "object_key": object_key,
        "manifest_object_key": manifest_key,
        "sha256": digest,
        "byte_size": len(content),
        "row_count": len(frame),
        "period_start": periods.min().strftime("%Y-%m"),
        "period_end": periods.max().strftime("%Y-%m"),
        "columns": list(frame.columns),
        "is_synthetic": True,
        "provenance_status": "synthetic",
        "training_eligible": False,
        "training_limitation": (
            "Synthetic dashboard data with fewer than the training pipeline's "
            "minimum monthly history periods is archived for reference only."
        ),
    }
    manifest = json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8")
    metadata["manifest_sha256"] = hashlib.sha256(manifest).hexdigest()

    existing = db.scalar(
        select(models.DatasetArchive).where(models.DatasetArchive.sha256 == digest)
    )
    if existing is not None:
        stored = read_object(
            existing.object_key,
            max_bytes=MAX_ARCHIVE_BYTES,
            backend="s3",
        )
        if hashlib.sha256(stored).hexdigest() != existing.sha256:
            raise ObjectStorageError("Existing dashboard archive failed SHA-256 verification.")
        stored_manifest = read_object(
            existing.metadata_json["manifest_object_key"],
            max_bytes=MAX_ARCHIVE_BYTES,
            backend="s3",
        )
        if (
            hashlib.sha256(stored_manifest).hexdigest()
            != existing.metadata_json.get("manifest_sha256")
        ):
            raise ObjectStorageError("Existing dashboard archive manifest failed SHA-256 verification.")
        return existing

    _write_immutable_object(object_key, content)
    _write_immutable_object(manifest_key, manifest)
    record = models.DatasetArchive(
        archive_id=archive_id,
        source_name=csv_path.name,
        object_key=object_key,
        sha256=digest,
        byte_size=len(content),
        row_count=len(frame),
        period_start=metadata["period_start"],
        period_end=metadata["period_end"],
        is_synthetic=True,
        metadata_json=metadata,
    )
    try:
        db.add(record)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive the existing synthetic dashboard CSV to Cloudflare R2."
    )
    parser.add_argument("--csv", type=Path, help="Dashboard CSV path (defaults to MEDIPREDICT_CSV_PATH).")
    args = parser.parse_args()
    with SessionLocal() as session:
        record = archive_dashboard_csv(session, source_path=args.csv)
    print(
        f"SYNTHETIC - archived dashboard CSV {record.archive_id}; "
        f"rows={record.row_count}; SHA-256={record.sha256}; "
        f"R2 key={record.object_key}"
    )


if __name__ == "__main__":
    main()
