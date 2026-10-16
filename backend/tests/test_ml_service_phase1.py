import asyncio
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
        "Rule-based days-of-cover estimate using fixed thresholds (<7, 7-14, >14 days). "
        "Not a probability."
    )
    assert result["data_source"] == "synthetic"
    assert result["is_synthetic"] is True


def test_unvalidated_artifact_is_rejected_and_fallback_used(
    monkeypatch, tmp_path, caplog
):
    _set_artifact_paths(monkeypatch, tmp_path, {"accuracy": 0.9875})

    with caplog.at_level(logging.WARNING, logger="backend.app.ml_service"):
        result = ml_service.infer([_record()])[0]

    assert result["method"] == "rule_based_fallback"
    assert result["model_validated"] is False
    assert (
        "time_based_split, test_metrics, training_date_range, data_hash, "
        "feature_list, horizon_days, is_synthetic"
    ) in caplog.text
    assert ml_service.load_metrics()["accuracy"] is None
    assert "0.9875" not in json.dumps(ml_service.load_metrics())


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


def test_metrics_api_withholds_legacy_accuracy(monkeypatch, tmp_path):
    _set_artifact_paths(monkeypatch, tmp_path, {"accuracy": 0.9875})

    response = asyncio.run(trust_metrics()).model_dump()

    assert response["accuracy"] is None
    assert "No validated model metrics" in response["source"]
    assert "0.9875" not in json.dumps(response)
