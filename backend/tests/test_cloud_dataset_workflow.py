import asyncio
import hashlib
import io
import json
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app import main, models
from backend.app.config import settings
from backend.app.database import Base
from ml import archive_dashboard_csv, train_registered_dataset


def _read_tampered_object(key, *, max_bytes, backend):
    assert key
    assert max_bytes > 0
    assert backend == "s3"
    return b"tampered"


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'workflow.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _dashboard_csv(path: Path, *, synthetic: str = "true") -> Path:
    path.write_text(
        "reporting_month,facility_name,medicine_code,end_of_month_stock_units,"
        "avg_daily_consumption_units,is_synthetic\n"
        f"2026-01,TEST-FAC-001,TEST-MED-001,25,2,{synthetic}\n"
        f"2026-02,TEST-FAC-001,TEST-MED-001,20,2,{synthetic}\n",
        encoding="utf-8",
    )
    return path


def test_archive_dashboard_csv_uploads_immutable_synthetic_source_and_manifest(
    tmp_path,
    monkeypatch,
    db_session,
):
    csv_path = _dashboard_csv(tmp_path / "dashboard.csv")
    objects: dict[str, bytes] = {}

    def write_object(key, content, *, backend=None):
        assert backend == "s3"
        if key in objects:
            raise archive_dashboard_csv.ObjectStorageError("Object already exists.")
        objects[key] = content

    def read_object(key, *, max_bytes, backend=None):
        assert backend == "s3"
        content = objects[key]
        assert len(content) <= max_bytes
        return content

    monkeypatch.setattr(settings, "database_enabled", True)
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(archive_dashboard_csv, "write_object", write_object)
    monkeypatch.setattr(archive_dashboard_csv, "read_object", read_object)

    record = archive_dashboard_csv.archive_dashboard_csv(
        db_session,
        source_path=csv_path,
    )

    assert record.is_synthetic is True
    assert record.row_count == 2
    assert record.period_start == "2026-01"
    assert record.period_end == "2026-02"
    assert record.metadata_json["training_eligible"] is False
    assert record.metadata_json["manifest_sha256"] == hashlib.sha256(
        objects[record.metadata_json["manifest_object_key"]]
    ).hexdigest()
    assert hashlib.sha256(objects[record.object_key]).hexdigest() == record.sha256
    assert record.metadata_json["manifest_object_key"] in objects
    manifest = objects[record.metadata_json["manifest_object_key"]].decode()
    assert '"provenance_status": "synthetic"' in manifest

    repeated = archive_dashboard_csv.archive_dashboard_csv(
        db_session,
        source_path=csv_path,
    )
    assert repeated.archive_id == record.archive_id
    assert len(objects) == 2


def test_archive_refuses_non_synthetic_or_non_r2_data(
    tmp_path,
    monkeypatch,
    db_session,
):
    csv_path = _dashboard_csv(tmp_path / "dashboard.csv", synthetic="false")
    monkeypatch.setattr(settings, "database_enabled", True)
    monkeypatch.setattr(settings, "storage_backend", "s3")

    with pytest.raises(ValueError, match="all-synthetic"):
        archive_dashboard_csv.archive_dashboard_csv(db_session, source_path=csv_path)

    monkeypatch.setattr(settings, "storage_backend", "local")
    with pytest.raises(RuntimeError, match="MEDIPREDICT_STORAGE_BACKEND=s3"):
        archive_dashboard_csv.archive_dashboard_csv(db_session, source_path=csv_path)


def _registered_dataset(db_session) -> models.DatasetRecord:
    record = models.DatasetRecord(
        dataset_id="v1-20261029T000000Z-" + "a" * 32,
        sha256="b" * 64,
        object_key="v1/dataset/data.csv",
        storage_backend="s3",
        byte_size=10,
        row_count=100,
        date_start="2025-01-01",
        date_end="2026-01-01",
        data_frequency="monthly",
        is_synthetic=True,
        data_source="uploaded",
        uploader="TEST-UPLOADER",
        metadata_json={"dataset_id": "v1-20261029T000000Z-" + "a" * 32},
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_manual_training_stores_candidate_and_feature_archives_in_r2(
    tmp_path,
    monkeypatch,
    db_session,
):
    source_record = _registered_dataset(db_session)
    objects: dict[str, bytes] = {}

    def write_object(key, content, *, backend=None):
        assert backend == "s3"
        assert key not in objects
        objects[key] = content

    def read_object(key, *, max_bytes, backend=None):
        assert backend == "s3"
        assert len(objects[key]) <= max_bytes
        return objects[key]

    @contextmanager
    def dataset_workspace(record, session):
        assert record.dataset_id == source_record.dataset_id
        assert session is db_session
        yield tmp_path / "temporary-uploads"

    feature_roots: list[Path] = []

    def build_dataset(dataset_id, *, uploads_root, output_root):
        assert dataset_id == source_record.dataset_id
        assert uploads_root == tmp_path / "temporary-uploads"
        feature_roots.append(output_root)
        feature_dir = output_root / dataset_id / "v1-feature-build"
        feature_dir.mkdir(parents=True)
        (feature_dir / "features.csv").write_text("feature,target\n1,0\n", encoding="utf-8")
        (feature_dir / "report.md").write_text("SYNTHETIC test report\n", encoding="utf-8")
        (feature_dir / "metadata.json").write_text(
            '{"feature_table_sha256":"%s"}' % ("c" * 64),
            encoding="utf-8",
        )
        return feature_dir

    def train_feature_dataset(
        feature_build_id,
        *,
        feature_root,
        model_root,
        minimum_history_periods,
        bootstrap_repetitions,
    ):
        assert feature_build_id == "v1-feature-build"
        assert feature_root == feature_roots[0]
        assert minimum_history_periods == 24
        assert bootstrap_repetitions == 1000
        model_dir = model_root / "20261029T000000Z-model"
        model_dir.mkdir(parents=True)
        model_file = model_dir / "model.joblib"
        model_file.write_bytes(b"synthetic model artifact")
        model_digest = hashlib.sha256(model_file.read_bytes()).hexdigest()
        (model_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "model_version": model_dir.name,
                    "source_dataset_id": source_record.dataset_id,
                    "data_hash": source_record.sha256,
                    "is_synthetic": True,
                    "model_validated": False,
                    "artifact_sha256": {"model.joblib": model_digest},
                }
            ),
            encoding="utf-8",
        )
        (model_dir / "report.md").write_text("SYNTHETIC evaluation\n", encoding="utf-8")
        return model_dir

    monkeypatch.setattr(settings, "database_enabled", True)
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(train_registered_dataset, "_dataset_workspace", dataset_workspace)
    monkeypatch.setattr(train_registered_dataset, "build_dataset", build_dataset)
    monkeypatch.setattr(
        train_registered_dataset,
        "train_feature_dataset",
        train_feature_dataset,
    )
    monkeypatch.setattr(train_registered_dataset, "write_object", write_object)
    monkeypatch.setattr(train_registered_dataset, "read_object", read_object)

    release = train_registered_dataset.train_registered_dataset(
        source_record.dataset_id,
        db_session,
    )

    assert release.release_status == "candidate"
    assert release.is_synthetic is True
    assert release.model_validated is False
    assert release.metadata_json["training_policy"] == "manual_review_required"
    assert release.artifact_key in objects
    assert release.metadata_json["feature_bundle_key"] in objects
    with ZipFile(io.BytesIO(objects[release.artifact_key])) as bundle:
        assert {"model.joblib", "metadata.json", "report.md"} == set(bundle.namelist())
    with ZipFile(io.BytesIO(objects[release.metadata_json["feature_bundle_key"]])) as bundle:
        assert {"features.csv", "metadata.json", "report.md"} == set(bundle.namelist())


def test_model_artifact_download_checks_hash_and_requires_admin(
    monkeypatch,
    db_session,
):
    model_version = "20261029T000000Z-model"
    release = models.ModelRelease(
        model_version=model_version,
        source_dataset_id=None,
        source_dataset_sha256="b" * 64,
        artifact_key="artifacts/models/candidate.zip",
        model_sha256="c" * 64,
        metadata_json={
            "model_bundle_key": "artifacts/models/candidate.zip",
            "model_bundle_sha256": hashlib.sha256(b"candidate").hexdigest(),
        },
        is_synthetic=True,
        model_validated=False,
        release_status="candidate",
    )
    db_session.add(release)
    db_session.commit()
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")

    def read_candidate(key, *, max_bytes, backend):
        assert key == "artifacts/models/candidate.zip"
        assert max_bytes > len(b"candidate")
        assert backend == "s3"
        return b"candidate"

    monkeypatch.setattr(
        main,
        "read_object",
        read_candidate,
    )

    response = asyncio.run(
        main.download_model_artifacts(
            model_version,
            x_admin_api_key="test-admin-key",
            db=db_session,
        )
    )
    assert response.status_code == 200
    assert response.body == b"candidate"
    assert response.headers["content-type"] == "application/zip"

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.download_model_artifacts(
                model_version,
                x_admin_api_key="wrong-key",
                db=db_session,
            )
        )
    assert error.value.status_code == 403

    monkeypatch.setattr(main, "read_object", _read_tampered_object)
    with pytest.raises(HTTPException, match="SHA-256"):
        asyncio.run(
            main.download_model_artifacts(
                model_version,
                x_admin_api_key="test-admin-key",
                db=db_session,
            )
        )


def test_dataset_download_checks_hash_and_requires_admin(
    monkeypatch,
    db_session,
):
    dataset = _registered_dataset(db_session)
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")

    def read_dataset(key, *, max_bytes, backend):
        assert key == dataset.object_key
        assert max_bytes >= len(b"dataset")
        assert backend == "s3"
        return b"dataset"

    monkeypatch.setattr(
        main,
        "read_object",
        read_dataset,
    )
    dataset.sha256 = hashlib.sha256(b"dataset").hexdigest()
    db_session.commit()

    response = asyncio.run(
        main.download_registered_dataset(
            dataset.dataset_id,
            x_admin_api_key="test-admin-key",
            db=db_session,
        )
    )
    assert response.body == b"dataset"
    assert response.headers["content-type"].startswith("text/csv")

    monkeypatch.setattr(main, "read_object", _read_tampered_object)
    with pytest.raises(HTTPException, match="SHA-256"):
        asyncio.run(
            main.download_registered_dataset(
                dataset.dataset_id,
                x_admin_api_key="test-admin-key",
                db=db_session,
            )
        )


def test_archived_dashboard_download_checks_hash(monkeypatch, db_session):
    content = b"reporting_month,is_synthetic\n2026-01,true\n"
    digest = hashlib.sha256(content).hexdigest()
    manifest_content = b'{"provenance_status":"synthetic"}'
    manifest_key = f"archives/dashboard/{digest}/dashboard.csv.metadata.json"
    archive = models.DatasetArchive(
        archive_id=f"dashboard-{digest}",
        source_name="dashboard.csv",
        object_key=f"archives/dashboard/{digest}/dashboard.csv",
        sha256=digest,
        byte_size=len(content),
        row_count=1,
        period_start="2026-01",
        period_end="2026-01",
        is_synthetic=True,
        metadata_json={
            "provenance_status": "synthetic",
            "manifest_object_key": manifest_key,
            "manifest_sha256": hashlib.sha256(manifest_content).hexdigest(),
        },
    )
    db_session.add(archive)
    db_session.commit()
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
    monkeypatch.setattr(
        main,
        "read_object",
        lambda key, *, max_bytes, backend: (
            (manifest_content if key == manifest_key else content)
            if max_bytes > 0 and backend == "s3"
            else b""
        ),
    )

    response = asyncio.run(
        main.download_dataset_archive(
            archive.archive_id,
            x_admin_api_key="test-admin-key",
            db=db_session,
        )
    )
    assert response.body == content
    assert response.headers["content-type"].startswith("text/csv")

    manifest_response = asyncio.run(
        main.download_dataset_archive_manifest(
            archive.archive_id,
            x_admin_api_key="test-admin-key",
            db=db_session,
        )
    )
    assert manifest_response.body == manifest_content
    assert manifest_response.headers["content-type"] == "application/json"

    monkeypatch.setattr(main, "read_object", _read_tampered_object)
    with pytest.raises(HTTPException, match="SHA-256"):
        asyncio.run(
            main.download_dataset_archive(
                archive.archive_id,
                x_admin_api_key="test-admin-key",
                db=db_session,
            )
        )
