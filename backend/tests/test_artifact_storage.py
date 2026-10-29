import hashlib
import json
from zipfile import ZipFile

from backend.app.config import settings
from backend.app.storage import read_object
from ml.artifact_storage import (
    store_feature_directory,
    store_model_directory,
    store_synthetic_dataset,
)


def test_synthetic_dataset_and_training_artifacts_use_configured_storage(
    tmp_path, monkeypatch
):
    storage_root = tmp_path / "objects"
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "uploads_path", storage_root)

    dataset_id = "v1-20261029T000000Z-" + "a" * 32
    dataset_dir = tmp_path / "synthetic" / dataset_id
    dataset_dir.mkdir(parents=True)
    dataset_bytes = b"date,is_synthetic\n2026-01-01,true\n"
    (dataset_dir / "data.csv").write_bytes(dataset_bytes)
    dataset_metadata = {
        "dataset_id": dataset_id,
        "sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "is_synthetic": True,
        "data_source": "synthetic_generated",
    }
    (dataset_dir / "metadata.json").write_text(json.dumps(dataset_metadata))

    dataset_hashes = store_synthetic_dataset(dataset_dir)

    assert dataset_hashes == (
        hashlib.sha256(dataset_bytes).hexdigest(),
        hashlib.sha256((dataset_dir / "metadata.json").read_bytes()).hexdigest(),
    )
    assert read_object(
        f"datasets/synthetic_generated/{dataset_id}/data.csv",
        max_bytes=1024,
    ) == dataset_bytes
    stored_metadata = json.loads(
        read_object(
            f"datasets/synthetic_generated/{dataset_id}/metadata.json",
            max_bytes=1024,
        )
    )
    assert stored_metadata["is_synthetic"] is True

    feature_dir = tmp_path / "features" / "build-1"
    feature_dir.mkdir(parents=True)
    (feature_dir / "features.csv").write_text("feature,is_synthetic\n1,true\n")
    (feature_dir / "metadata.json").write_text(
        json.dumps({"build_id": "build-1", "is_synthetic": True})
    )
    feature_hash = store_feature_directory(feature_dir)

    model_dir = tmp_path / "models" / "candidate-1"
    model_dir.mkdir(parents=True)
    (model_dir / "model.joblib").write_bytes(b"synthetic model")
    (model_dir / "metadata.json").write_text(
        json.dumps({"model_version": "candidate-1", "is_synthetic": True})
    )
    model_hash = store_model_directory(model_dir)

    feature_key = "artifacts/features/build-1/feature-table.zip"
    model_key = "artifacts/models/candidate-1/candidate.zip"
    assert len(feature_hash) == len(model_hash) == 64
    assert (storage_root / feature_key).is_file()
    assert (storage_root / model_key).is_file()
    with ZipFile(storage_root / feature_key) as archive:
        assert "features.csv" in archive.namelist()
        assert "metadata.json" in archive.namelist()
    with ZipFile(storage_root / model_key) as archive:
        metadata = json.loads(archive.read("metadata.json"))
        assert metadata["is_synthetic"] is True
