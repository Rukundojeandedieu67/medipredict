import asyncio
import hashlib
import io
import json
import logging

import pytest
from fastapi import HTTPException, UploadFile

from backend.app import ml_service
from backend.app.main import assess_csv, trust_metrics, upload_csv


def _record(is_synthetic: bool = True) -> dict:
    return {
        "facility": "Facility A",
        "district": "Gasabo",
        "province": "Kigali",
        "facility_type": "Health Center",
        "medicine_code": "MED-1",
        "medicine": "Medicine A",
        "stock_units": 40,
        "daily_consumption": 5,
        "under5_population": 100,
        "poverty_rate": 10.0,
        "malaria_prevalence": 1.0,
        "rainy_season": 0,
        "reporting_date": "2026-01",
        "is_synthetic": is_synthetic,
    }


@pytest.fixture(autouse=True)
def clear_model_cache():
    ml_service.get_model_bundle.cache_clear()
    yield
    ml_service.get_model_bundle.cache_clear()


def _set_artifact_paths(monkeypatch, tmp_path, metadata=None):
    model_path = tmp_path / "legacy-model.joblib"
    model_path.write_bytes(b"not loaded for an invalid artifact")
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(metadata or {}), encoding="utf-8")
    monkeypatch.setattr(ml_service.settings, "model_path", model_path)
    monkeypatch.setattr(ml_service.settings, "metrics_path", metrics_path)


def _upload_file(csv_text: str) -> UploadFile:
    return UploadFile(filename="assessment.csv", file=io.BytesIO(csv_text.encode("utf-8")))


def _csv_row(is_synthetic: str | None) -> str:
    columns = [
        "facility_id",
        "item_id",
        "date",
        "stock_on_hand",
        "units_consumed",
        "units_received",
    ]
    values = {
        "facility_id": "FAC-1",
        "item_id": "MED-1",
        "date": "2026-01-01",
        "stock_on_hand": "40",
        "units_consumed": "5",
        "units_received": "0",
    }
    if is_synthetic is not None:
        columns.append("is_synthetic")
        values["is_synthetic"] = is_synthetic
    return ",".join(columns) + "\n" + ",".join(values[column] for column in columns)


def test_fallback_has_no_confidence_and_is_explicitly_rule_based(monkeypatch, tmp_path):
    monkeypatch.setattr(ml_service.settings, "model_path", tmp_path / "missing.joblib")
    result = ml_service.infer([_record()])[0]

    assert result["method"] == "rule_based_fallback"
    assert result["model_version"] is None
    assert result["model_validated"] is False
    assert result["confidence"] is None
    assert result["confidence_note"] == (
        "Stock-cover estimate uses reported stock and average daily consumption. "
        "Assumes constant consumption and no incoming receipts; not a probability."
    )
    assert result["lead_time_days"] == 8
    assert result["estimated_stock_after_7_days"] == 5
    assert result["estimated_stock_after_14_days"] == 0
    assert result["data_source"] == "synthetic"
    assert result["is_synthetic"] is True
    assert result["provenance_status"] == "synthetic"


def test_non_synthetic_serving_records_are_unverified_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(ml_service.settings, "model_path", tmp_path / "missing.joblib")

    result = ml_service.infer([_record(is_synthetic=False)])[0]

    assert result["provenance_status"] == "uploaded_unverified"


@pytest.mark.parametrize(
    ("stock", "consumption", "days", "expected"),
    [
        (100, 4, 7, 72),
        (50, 5, 14, 0),
        (0, 0, 7, 0),
        (100, 0, 7, None),
        (-1, 2, 7, None),
        (100, float("nan"), 7, None),
    ],
)
def test_stock_projection_uses_available_stock_and_safe_bounds(
    stock, consumption, days, expected
):
    assert ml_service.estimate_stock_after_days(stock, consumption, days) == expected


def test_recorded_stockout_is_critical_even_when_current_cover_exceeds_threshold(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(ml_service.settings, "model_path", tmp_path / "missing.joblib")
    record = {**_record(), "stockout_flag": True}

    result = ml_service.infer([record])[0]

    assert result["lead_time_days"] == 8
    assert result["risk_level"] == "CRITICAL"


def test_unvalidated_artifact_is_rejected_and_fallback_used(
    monkeypatch, tmp_path, caplog
):
    _set_artifact_paths(monkeypatch, tmp_path, {"accuracy": 0.9875})

    with caplog.at_level(logging.WARNING, logger="backend.app.ml_service"):
        assert ml_service.get_model_bundle() == (None, None)
        result = ml_service.infer([_record()])[0]

    assert result["method"] == "rule_based_fallback"
    assert result["model_validated"] is False
    assert (
        "time_based_split, test_metrics, training_date_range, data_hash, "
        "feature_list, horizon_days, is_synthetic"
    ) in caplog.text
    assert ml_service.load_metrics()["accuracy"] is None
    assert "0.9875" not in json.dumps(ml_service.load_metrics())


@pytest.mark.parametrize(
    ("model_validated", "expected_hash", "warning"),
    [
        (False, "0" * 64, "model_validated is not true"),
        (True, "0" * 64, "SHA-256 mismatch"),
    ],
)
def test_model_artifact_requires_validation_and_matching_hash(
    monkeypatch, tmp_path, caplog, model_validated, expected_hash, warning
):
    _set_artifact_paths(
        monkeypatch,
        tmp_path,
        {
            "time_based_split": True,
            "test_metrics": {"pr_auc": 0.5, "roc_auc": 0.5},
            "training_date_range": {"start": "2025-01-01", "end": "2025-12-31"},
            "data_hash": "a" * 64,
            "feature_list": ["stock_lag"],
            "horizon_days": 7,
            "is_synthetic": False,
            "model_validated": model_validated,
            "artifact_sha256": {"legacy-model.joblib": expected_hash},
        },
    )

    with caplog.at_level(logging.WARNING, logger="backend.app.ml_service"):
        assert ml_service.get_model_bundle() == (None, None)

    assert warning in caplog.text
    assert ml_service.infer([_record()])[0]["method"] == "rule_based_fallback"


def test_upload_without_synthetic_column_returns_required_validation_message():
    with pytest.raises(HTTPException) as error:
        asyncio.run(upload_csv(_upload_file(_csv_row(None))))

    assert error.value.status_code == 422
    assert (
        error.value.detail["validation"]["errors"][0]["message"]
        == "Column is_synthetic is required: true or false. "
        "Unknown data provenance is not accepted."
    )


def test_upload_with_invalid_synthetic_value_returns_4xx():
    with pytest.raises(HTTPException) as error:
        asyncio.run(upload_csv(_upload_file(_csv_row("unknown"))))

    assert error.value.status_code == 422
    assert error.value.detail["validation"]["errors"][0]["code"] == "INVALID_BOOLEAN"


@pytest.mark.parametrize(
    ("synthetic_flag", "expected_synthetic"),
    [("TrUe", True), ("FALSE", False)],
)
def test_upload_response_and_assessment_items_include_provenance_fields(
    monkeypatch, tmp_path, synthetic_flag, expected_synthetic
):
    monkeypatch.setattr(ml_service.settings, "model_path", tmp_path / "missing.joblib")

    result = asyncio.run(assess_csv(_upload_file(_csv_row(synthetic_flag))))
    response = result.model_dump()

    expected = {
        "method",
        "model_version",
        "model_validated",
        "data_source",
        "is_synthetic",
        "confidence_note",
    }
    assert expected.issubset(response)
    assert expected.issubset(response["items"][0])
    assert response["method"] == "rule_based_fallback"
    assert response["data_source"] == "uploaded"
    assert response["is_synthetic"] is expected_synthetic
    assert response["items"][0]["is_synthetic"] is expected_synthetic
    assert response["items"][0]["confidence"] is None
    assert response["items"][0]["estimated_stock_after_7_days"] == 5
    assert response["items"][0]["estimated_stock_after_14_days"] == 0


def test_metrics_api_withholds_legacy_accuracy(monkeypatch, tmp_path):
    _set_artifact_paths(monkeypatch, tmp_path, {"accuracy": 0.9875})

    response = asyncio.run(trust_metrics()).model_dump()

    assert response["accuracy"] is None
    assert "No validated model metrics" in response["source"]
    assert "0.9875" not in json.dumps(response)
    assert response["provenance_status"] == "uploaded_unverified"
    assert response["model_validated"] is False


def test_model_loader_reports_live_provenance_and_downgrades_tampering(
    monkeypatch, tmp_path
):
    from backend.app import provenance

    dataset_id = "v1-20260101T000000Z-" + "b" * 32
    uploads = tmp_path / "uploads"
    dataset_dir = uploads / "v1" / dataset_id
    dataset_dir.mkdir(parents=True)
    content = (
        "facility_id,item_id,date,stock_on_hand,units_consumed,units_received,is_synthetic\n"
        "TEST-FAC-001,TEST-ITEM-001,0001-01-01,10,1,0,false\n"
    ).encode()
    digest = hashlib.sha256(content).hexdigest()
    (dataset_dir / "data.csv").write_bytes(content)
    (dataset_dir / "metadata.json").write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "sha256": digest,
                "is_synthetic": False,
                "uploader_identity": "TEST-UPLOADER-001",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "approved_sources.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "TEST-SOURCE-001",
                        "name": "TEST SOURCE",
                        "organization": "TEST ORGANIZATION",
                        "system": "TEST SYSTEM",
                        "contact": "",
                        "accepted_verification_methods": ["direct_export_from_system"],
                        "notes": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    verification = provenance.verify_dataset(
        dataset_id,
        uploads,
        source_id="TEST-SOURCE-001",
        verification_method="direct_export_from_system",
        verification_reference="TEST-REF-001",
        reporting_period_start="0001-01-01",
        reporting_period_end="0001-01-01",
        verified_by="TEST-VERIFIER-001",
    )["verification"]
    model_path = tmp_path / "test-model.joblib"
    model_content = b"test model"
    model_path.write_bytes(model_content)
    metrics_path = tmp_path / "model-metadata.json"
    metrics_path.write_text(
        json.dumps(
            {
                "artifact_sha256": {
                    model_path.name: hashlib.sha256(model_content).hexdigest()
                },
                "time_based_split": True,
                "test_metrics": {"pr_auc": 0.7, "roc_auc": 0.8},
                "training_date_range": {"start": "0001-01-01", "end": "0001-01-01"},
                "data_hash": digest,
                "verified_dataset_hash": digest,
                "source_dataset_id": dataset_id,
                "provenance_status": "verified",
                "verification": verification,
                "feature_list": ["days_of_cover"],
                "horizon_days": 14,
                "is_synthetic": False,
                "model_validated": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ml_service.settings, "uploads_path", uploads)
    monkeypatch.setattr(ml_service.settings, "model_path", model_path)
    monkeypatch.setattr(ml_service.settings, "metrics_path", metrics_path)
    monkeypatch.setattr(ml_service.joblib, "load", lambda _: "TEST MODEL")
    ml_service.get_model_bundle.cache_clear()

    model, metadata = ml_service.get_model_bundle()
    assert model == "TEST MODEL"
    assert metadata["provenance_status"] == "verified"
    assert metadata["model_validated"] is True

    with (dataset_dir / "data.csv").open("ab") as destination:
        destination.write(b"#changed\n")
    ml_service.get_model_bundle.cache_clear()

    _, changed_metadata = ml_service.get_model_bundle()
    metrics = ml_service.load_metrics()
    assert changed_metadata["provenance_status"] == "uploaded_unverified"
    assert changed_metadata["model_validated"] is False
    assert metrics["provenance_status"] == "uploaded_unverified"
    assert metrics["model_validated"] is False
