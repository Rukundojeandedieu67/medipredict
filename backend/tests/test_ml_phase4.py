from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from ml.build_dataset import build_dataset
from ml.promote import evaluate_promotion_gate
from ml.synthetic import generate_synthetic_supply_history
from ml.train import (
    TestSetAccessGuard,
    _resolve_feature_table,
    _subgroups,
    _preprocessors,
)
from backend.app.validation import ValidationConfig, validate_inventory_csv
from backend.app import ml_service
from ml.train import _create_artifact_directory

ROOT = Path(__file__).resolve().parents[2]


def test_monthly_minimum_history_defaults_to_24_and_is_configurable():
    assert ValidationConfig(data_frequency="monthly").minimum_records_per_facility_item == 24
    assert ValidationConfig(
        data_frequency="monthly", minimum_records_per_facility_item=36
    ).minimum_records_per_facility_item == 36


def test_synthetic_generator_produces_dynamics_and_provenance():
    generated = generate_synthetic_supply_history(
        facilities=6, periods=420, seed=19
    )

    assert generated["is_synthetic"].all()
    assert generated["stockout_flag"].any()
    opening_stock = (
        generated.groupby("facility_id", sort=False)["stock_on_hand"].shift(1).fillna(
            generated.groupby("facility_id", sort=False)["stock_on_hand"].transform("first")
        )
        + generated["units_received"]
    )
    assert (generated["units_consumed"] <= opening_stock + 1e-6).all()
    assert generated["date"].nunique() == 420


def test_validation_preprocessing_is_fit_on_training_rows_only():
    training = pd.DataFrame(
        {"numeric": [1.0, 2.0, np.nan], "category": ["a", "b", "a"]}
    )
    validation = pd.DataFrame({"numeric": [1000.0], "category": ["new"]})
    altered_validation = pd.DataFrame({"numeric": [-5000.0], "category": ["other"]})
    logistic, _ = _preprocessors(training)
    logistic.fit(training)
    original_stats = logistic.named_transformers_["numeric"].named_steps["imputer"].statistics_.copy()
    original_levels = logistic.named_transformers_["categorical"].named_steps["encoder"].categories_

    logistic.transform(validation)
    logistic.transform(altered_validation)

    np.testing.assert_equal(
        original_stats,
        logistic.named_transformers_["numeric"].named_steps["imputer"].statistics_,
    )
    assert original_levels == logistic.named_transformers_["categorical"].named_steps["encoder"].categories_


def test_test_set_access_guard_allows_exactly_one_access():
    read = []

    def load():
        read.append(True)
        return pd.DataFrame({"target": [0, 1]})

    guard = TestSetAccessGuard(load)
    assert not read
    assert len(guard.evaluate_once()) == 2
    assert len(read) == 1
    with pytest.raises(RuntimeError, match="only once"):
        guard.evaluate_once()
    assert guard.access_count == 1


def test_artifact_directory_creation_refuses_overwrite(tmp_path):
    existing = tmp_path / "immutable-version"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        _create_artifact_directory(tmp_path, "immutable-version")


def test_training_accepts_only_registered_build_ids(tmp_path):
    with pytest.raises(ValueError, match="build ID"):
        _resolve_feature_table(str(tmp_path), tmp_path)


def test_subgroups_below_minimum_positive_count_are_not_scored():
    frame = pd.DataFrame(
        {
            "target": [1, 0, 1, 0],
            "facility_type": ["A", "A", "B", "B"],
        }
    )

    results = _subgroups(
        frame, scores=np.asarray([0.8, 0.2, 0.7, 0.1]),
        threshold=0.5, minimum_positives=2,
    )

    assert [row["status"] for row in results] == [
        "insufficient data", "insufficient data"
    ]
    assert all("recall" not in row for row in results)


def test_phase1_loader_rejects_synthetic_artifact_even_with_complete_metadata(
    tmp_path, monkeypatch
):
    model_path = tmp_path / "synthetic-model.joblib"
    model_path.write_text("not loaded", encoding="utf-8")
    metrics_path = tmp_path / "synthetic-metadata.json"
    metrics_path.write_text(
        json.dumps(
            {
                "time_based_split": True,
                "test_metrics": {"pr_auc": 0.7, "roc_auc": 0.8},
                "training_date_range": {"start": "2022-01-01", "end": "2023-01-01"},
                "data_hash": "sha256",
                "feature_list": ["days_of_cover"],
                "horizon_days": 14,
                "is_synthetic": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ml_service.settings, "model_path", model_path)
    monkeypatch.setattr(ml_service.settings, "metrics_path", metrics_path)
    ml_service.get_model_bundle.cache_clear()

    assert ml_service.get_model_bundle() == (None, None)

    ml_service.get_model_bundle.cache_clear()


@pytest.mark.parametrize(
    ("synthetic", "time_split", "test_metrics", "diagnostics", "failed"),
    [
        (
            True, True,
            {"rule_baseline": {"pr_auc": 0.2, "recall": 0.1},
             "selected_model": {"pr_auc": 0.8, "roc_auc": 0.8, "recall": 0.7,
                                "brier": 0.1, "pr_auc_difference_vs_rule_ci": [0.1, 0.3]}},
            {"unseen_recall": 0.7, "leakage_warnings": []},
            "real_data",
        ),
        (
            False, True,
            {"rule_baseline": {"pr_auc": 0.2, "recall": 0.1},
             "selected_model": {"pr_auc": 0.8, "roc_auc": 0.8, "recall": 0.7,
                                "brier": 0.1, "pr_auc_difference_vs_rule_ci": [-0.1, 0.3]}},
            {"unseen_recall": 0.7, "leakage_warnings": []},
            "test_pr_auc_beats_rule_with_ci",
        ),
        (
            False, False,
            {"rule_baseline": {"pr_auc": 0.2, "recall": 0.8},
             "selected_model": {"pr_auc": 0.8, "roc_auc": 0.8, "recall": 0.4,
                                "brier": 0.4, "pr_auc_difference_vs_rule_ci": [0.1, 0.3]}},
            {"unseen_recall": 0.1, "leakage_warnings": ["future-stock"]},
            "time_based_split",
        ),
    ],
)
def test_promotion_gate_reports_each_failed_condition(
    synthetic, time_split, test_metrics, diagnostics, failed
):
    result = evaluate_promotion_gate(
        is_synthetic=synthetic,
        time_based_split=time_split,
        test_metrics=test_metrics,
        gate_diagnostics=diagnostics,
    )

    assert failed in result["failed_criteria"]
    if synthetic:
        assert result["model_validated"] is False


@pytest.mark.parametrize(
    "criterion",
    [
        "real_data",
        "time_based_split",
        "test_pr_auc_beats_rule_with_ci",
        "recall_beats_rule_at_fixed_precision",
        "calibration_within_limit",
        "unseen_facility_within_tolerance",
        "no_phase3_leakage_warnings",
    ],
)
def test_promotion_gate_rejects_each_failed_criterion(criterion):
    test_metrics = {
        "rule_baseline": {"pr_auc": 0.3, "recall": 0.4},
        "selected_model": {
            "pr_auc": 0.6, "roc_auc": 0.7, "recall": 0.8, "brier": 0.1,
            "pr_auc_difference_vs_rule_ci": [0.1, 0.4],
        },
    }
    diagnostics = {"unseen_recall": 0.8, "leakage_warnings": []}
    synthetic = False
    time_split = True
    if criterion == "real_data":
        synthetic = True
    elif criterion == "time_based_split":
        time_split = False
    elif criterion == "test_pr_auc_beats_rule_with_ci":
        test_metrics["selected_model"]["pr_auc_difference_vs_rule_ci"] = [-0.1, 0.2]
    elif criterion == "recall_beats_rule_at_fixed_precision":
        test_metrics["selected_model"]["recall"] = 0.2
    elif criterion == "calibration_within_limit":
        test_metrics["selected_model"]["brier"] = 0.9
    elif criterion == "unseen_facility_within_tolerance":
        diagnostics["unseen_recall"] = 0.1
    elif criterion == "no_phase3_leakage_warnings":
        diagnostics["leakage_warnings"] = ["future stock"]

    result = evaluate_promotion_gate(
        is_synthetic=synthetic,
        time_based_split=time_split,
        test_metrics=test_metrics,
        gate_diagnostics=diagnostics,
    )

    assert criterion in result["failed_criteria"]


def _build_synthetic_feature_table(uploads_root: Path, output_root: Path) -> str:
    source = generate_synthetic_supply_history(
        facilities=6, periods=900, seed=17
    )
    config = ValidationConfig(
        minimum_records_per_facility_item=90,
        minimum_facility_items=1,
    )
    validation = validate_inventory_csv(source, purpose="training", config=config)
    assert validation["valid"] is True
    dataset_id = "v1-20261016T120000Z-" + "b" * 32
    upload_dir = uploads_root / "v1" / dataset_id
    upload_dir.mkdir(parents=True)
    data_path = upload_dir / "data.csv"
    source.to_csv(data_path, index=False)
    registry = {
        "dataset_id": dataset_id,
        "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "row_count": len(source),
        "date_range": validation["date_range"],
        "is_synthetic": True,
        "data_source": "uploaded",
        "data_frequency": "daily",
    }
    (upload_dir / "metadata.json").write_text(
        json.dumps(registry, indent=2), encoding="utf-8"
    )
    built = build_dataset(
        dataset_id,
        minimum_records_per_facility_item=90,
        minimum_facility_items=1,
        minimum_positives=1,
        uploads_root=uploads_root,
        output_root=output_root,
    )
    return json.loads((built / "metadata.json").read_text(encoding="utf-8"))["build_id"]


def test_synthetic_end_to_end_training_is_unvalidated_and_versioned(tmp_path):
    feature_root = tmp_path / "features"
    upload_root = tmp_path / "uploads"
    build_id = _build_synthetic_feature_table(upload_root, feature_root)
    output_root = tmp_path / "models"

    command = [
        sys.executable, "-m", "ml.train", build_id,
        "--feature-root", str(feature_root),
        "--model-root", str(output_root),
        "--minimum-split-positives", "1",
        "--bootstrap-repetitions", "10",
    ]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=True
    )
    artifact_path = completed.stdout.strip().split("Artifact saved: ")[-1]
    artifact = Path(artifact_path)

    metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
    report = json.loads((artifact / "evaluation_report.json").read_text(encoding="utf-8"))
    assert metadata["notice"].startswith("SYNTHETIC - not evidence of real-world performance")
    assert metadata["is_synthetic"] is True
    assert metadata["model_validated"] is False
    assert metadata["test_access_count"] == 1
    assert metadata["test_metrics"]["pr_auc"] is not None
    assert metadata["test_metrics"]["roc_auc"] is not None
    assert metadata["test_metrics"]["pr_auc"] > metadata["all_test_metrics"]["rule_baseline"]["pr_auc"]
    assert metadata["all_test_metrics"]["logistic_regression"]["pr_auc_difference_vs_rule_ci"]
    assert metadata["all_test_metrics"]["rule_baseline"]["cluster_bootstrap_95_ci"]["pr_auc"]
    assert metadata["all_test_metrics"]["persistence_baseline"]["cluster_bootstrap_95_ci"]["pr_auc"]
    assert metadata["feature_builder_state"]["feature_list"] == metadata["feature_list"]
    assert metadata["test_metrics"]["recall_at_fixed_precision"] == metadata["test_metrics"]["recall"]
    assert metadata["unseen_group"]["results"]["status"] == "computed"
    assert {
        "time_based_split", "test_metrics", "training_date_range", "data_hash",
        "feature_list", "horizon_days", "data_frequency", "is_synthetic",
        "threshold", "gate_results", "model_validated", "library_versions",
        "random_seed", "git_commit",
    }.issubset(metadata)
    assert report["gate_results"]["model_validated"] is False
    assert (artifact / "model.joblib").is_file()
    assert (artifact / "evaluation_report.md").read_text(encoding="utf-8").startswith(
        "# SYNTHETIC - not evidence of real-world performance"
    )

