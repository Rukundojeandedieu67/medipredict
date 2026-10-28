import asyncio
import hashlib
import io
import json
import logging

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import main
from backend.app.database import Base
from backend.app.validation import ValidationConfig, validate_inventory_csv


def _csv(rows=1, *, synthetic="false", invalid=False, include_synthetic=True) -> bytes:
    columns = "facility_id,item_id,date,stock_on_hand,units_consumed,units_received"
    if include_synthetic:
        columns += ",is_synthetic"
    lines = [columns]
    for index in range(rows):
        flag = "unknown" if invalid else synthetic
        row = f"FAC-1,ITEM-{index},2026-01-{index + 1:02d},20,2,0"
        lines.append(f"{row},{flag}" if include_synthetic else row)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _upload(content: bytes) -> UploadFile:
    return UploadFile(filename="inventory.csv", file=io.BytesIO(content))


@pytest.fixture
def permissive_training_thresholds(monkeypatch):
    monkeypatch.setattr(main.settings, "training_min_records", 1)
    monkeypatch.setattr(main.settings, "training_min_facility_items", 1)


@pytest.fixture
def database_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'registry.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_assessment_endpoint_does_not_persist_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "uploads_path", tmp_path / "uploads")
    content = _csv()

    result = asyncio.run(main.assess_csv(_upload(content)))

    assert result.records_received == 1
    assert result.data_source == "uploaded"
    assert result.provenance_status == "uploaded_unverified"
    assert result.items[0].provenance_status == "uploaded_unverified"
    assert result.items[0].method == "rule_based_fallback"
    assert not (tmp_path / "uploads").exists()


def test_synthetic_assessment_uses_synthetic_status():
    result = asyncio.run(main.assess_csv(_upload(_csv(synthetic="true"))))

    assert result.provenance_status == "synthetic"
    assert result.items[0].provenance_status == "synthetic"
    assert result.validation.provenance_status == "synthetic"


@pytest.mark.parametrize(
    ("include_synthetic", "synthetic"),
    [(False, "false"), (True, "")],
    ids=("missing-flag-column", "blank-flag"),
)
def test_assessment_accepts_unknown_synthetic_flag_as_uploaded(
    include_synthetic, synthetic
):
    result = asyncio.run(
        main.assess_csv(
            _upload(
                _csv(
                    include_synthetic=include_synthetic,
                    synthetic=synthetic,
                )
            )
        )
    )

    assert result.records_received == 1
    assert result.data_source == "uploaded"
    assert result.is_synthetic is None
    assert result.provenance_status == "uploaded_unverified"
    assert result.items[0].is_synthetic is None
    assert result.items[0].provenance_status == "uploaded_unverified"


def test_legacy_upload_route_is_deprecated_assessment_alias(caplog):
    with caplog.at_level(logging.WARNING, logger="backend.app.main"):
        result = asyncio.run(main.upload_csv(_upload(_csv())))

    assert result.method == "rule_based_fallback"
    assert "Deprecated endpoint /api/v1/data/upload-csv" in caplog.text


def test_validate_endpoint_matches_pure_validator_output():
    content = _csv()
    frame = main.pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
    expected = validate_inventory_csv(frame, purpose="assessment")

    report = asyncio.run(main.validate_csv(_upload(content), purpose="assessment"))

    assert report.model_dump() == expected


def test_http_assess_and_validate_endpoints_return_contract_shapes(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "uploads_path", tmp_path / "uploads")
    content = _csv()

    with TestClient(main.app) as client:
        assessment = client.post(
            "/api/v1/data/assess-csv",
            files={"file": ("inventory.csv", content, "text/csv")},
        )
        validation = client.post(
            "/api/v1/data/validate-csv?purpose=assessment",
            files={"file": ("inventory.csv", content, "text/csv")},
        )

    assert assessment.status_code == 200
    assessment_json = assessment.json()
    assert assessment_json["method"] == "rule_based_fallback"
    assert assessment_json["items"][0]["data_source"] == "uploaded"
    assert assessment_json["provenance_status"] == "uploaded_unverified"
    assert assessment_json["items"][0]["provenance_status"] == "uploaded_unverified"
    assert assessment_json["items"][0]["confidence"] is None
    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert not (tmp_path / "uploads").exists()


def test_training_upload_rejects_bad_files(monkeypatch):
    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    monkeypatch.setattr(
        main,
        "_validation_config",
        lambda: ValidationConfig(minimum_records_per_facility_item=2, minimum_facility_items=1),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            main.training_upload(
                _upload(_csv(rows=1)),
                x_admin_api_key="test-secret",
                x_uploader=None,
            )
        )

    assert error.value.status_code == 422
    assert error.value.detail["validation"]["errors"][0]["code"] == "MINIMUM_HISTORY_RECORDS"


def test_training_upload_is_forbidden_without_admin_key(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "admin_api_key", "configured-secret")
    monkeypatch.setattr(main.settings, "uploads_path", tmp_path / "uploads")

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.training_upload(_upload(_csv()), x_admin_api_key=None, x_uploader=None))

    assert error.value.status_code == 403
    assert not (tmp_path / "uploads").exists()


def test_training_upload_hashes_data_and_never_overwrites(
    monkeypatch, tmp_path, permissive_training_thresholds, database_session
):
    content = _csv()
    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    monkeypatch.setattr(main.settings, "uploads_path", tmp_path / "uploads")

    first = asyncio.run(
        main.training_upload(
            _upload(content),
            x_admin_api_key="test-secret",
            x_uploader="test-operator",
            db=database_session,
        )
    )
    second = asyncio.run(
        main.training_upload(
            _upload(content),
            x_admin_api_key="test-secret",
            x_uploader="test-operator",
            db=database_session,
        )
    )

    assert first.dataset_id != second.dataset_id
    assert first.sha256 == hashlib.sha256(content).hexdigest()
    assert second.sha256 == first.sha256
    for result in (first, second):
        directory = tmp_path / "uploads" / "v1" / result.dataset_id
        assert (directory / "data.csv").read_bytes() == content
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["uploader"] == "test-operator"
        assert metadata["sha256"] == result.sha256
        assert metadata["data_source"] == "uploaded"
