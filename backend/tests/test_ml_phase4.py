from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys
import hashlib

import numpy as np
import pandas as pd
import pytest

from ml.build_dataset import build_dataset
from ml.features import FeatureBuilder
from ml.promote import evaluate_promotion_gate
from ml.missingness import profile_inventory_missingness
from ml.synthetic import generate_synthetic_supply_history
from ml.splits import assign_time_splits, time_based_split
from ml.train import (
    TestSetAccessGuard,
    _load_feature_table,
    _resolve_feature_table,
    _subgroups,
    _preprocessors,
    _validate_time_split_metadata,
    _threshold_for_precision,
    _training_validation_leakage_diagnostics,
    _validate_split_positives,
    _validate_training_history,
    _validation_policy,
    _rule_scores,
)
from ml.train_synthetic import prepare_synthetic_feature_dataset
from ml import train_uploaded_dataset
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
        facilities=6, periods=420, seed=19, frequency="daily"
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


def test_synthetic_generator_defaults_to_monthly_and_marks_every_row_synthetic():
    generated = generate_synthetic_supply_history(
        facilities=6, periods=36, seed=190
    )

    assert generated["date"].nunique() == 36
    assert generated["is_synthetic"].all()
    assert "stock_out_days" in generated
    assert generated["stock_out_days"].gt(0).any()


def test_monthly_rule_baseline_uses_seven_and_fourteen_day_equivalent_thresholds():
    rows = pd.DataFrame({"months_of_stock": [0.1, 0.25, 0.5, 0.51, np.nan]})

    scores = _rule_scores(rows, "monthly")

    np.testing.assert_array_equal(scores, [1.0, 0.5, 0.5, 0.0, -0.5])


def test_low_positive_validation_uses_platt_calibration():
    labels = np.asarray([0, 1, 0, 1, 0, 1])
    scores = np.asarray([0.1, 0.8, 0.2, 0.7, 0.3, 0.9])

    _, calibrator, _, _, details = _validation_policy(labels, scores, 0.5)

    assert details["method"] == "platt"
    assert details["fit_data"] == "validation predictions and labels only"
    assert calibrator is not None


def test_seasonal_features_are_disabled_below_24_training_months():
    source = generate_synthetic_supply_history(
        facilities=2, periods=24, seed=23
    )
    source = source.loc[source["date"] != source["date"].max()]

    builder = FeatureBuilder(frequency="monthly").fit(source)

    assert builder.state_dict()["seasonal_features_enabled"] is False
    assert "stockout_same_period_last_year" not in builder.feature_list
    assert "rwanda_season" not in builder.feature_list


def test_training_refuses_fewer_than_24_distinct_months():
    frame = pd.DataFrame(
        {
            "facility_id": ["F1", "F2"] * 23,
            "date": pd.date_range("2024-01-31", periods=23, freq="ME")
            .strftime("%Y-%m-%d")
            .repeat(2),
        }
    )

    with pytest.raises(ValueError, match="23 distinct months.*at least 24"):
        _validate_training_history(
            frame,
            frequency="monthly",
            minimum_history_periods=24,
            minimum_facilities=2,
        )


def test_training_refuses_split_below_configured_positive_minimum():
    frame = pd.DataFrame({"target": [1, 0, 0, 0]})

    with pytest.raises(ValueError, match="has 1 positives; at least 2"):
        _validate_split_positives(
            "validation",
            frame,
            minimum_positives=2,
        )


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


def test_test_row_changes_do_not_change_validation_calibrator_or_threshold():
    validation_y = np.asarray([0, 1, 0, 1, 0, 1] * 8)
    validation_scores = np.asarray([0.1, 0.8, 0.2, 0.7, 0.3, 0.9] * 8)
    test_rows = pd.DataFrame(
        {"feature": np.arange(10), "target": [0, 1] * 5}
    )
    first = _validation_policy(validation_y, validation_scores, 0.5)

    test_rows["feature"] = np.random.default_rng(42).normal(size=len(test_rows))
    test_rows["target"] = 1 - test_rows["target"]
    second = _validation_policy(validation_y, validation_scores, 0.5)

    assert first[2:4] == second[2:4]
    np.testing.assert_array_equal(first[0], second[0])
    np.testing.assert_array_equal(
        first[1].X_thresholds_, second[1].X_thresholds_
    )
    np.testing.assert_array_equal(
        first[1].y_thresholds_, second[1].y_thresholds_
    )


def test_unattainable_precision_target_is_reported_as_not_comparable():
    y = np.asarray([1, 0, 1, 0])
    scores = np.asarray([0.1, 0.2, 0.3, 0.4])
    threshold, selection = _threshold_for_precision(y, scores, 0.99)

    assert 0 <= threshold <= 1
    assert selection["selection"] == "maximum validation F1; precision target was unattainable"
    assert selection["precision_target_attained"] is False
    assert selection["validation_precision"] < 0.99

    gate = evaluate_promotion_gate(
        is_synthetic=False,
        time_based_split=True,
        test_metrics={
            "rule_baseline": {
                "pr_auc": 0.3,
                "recall": 0.5,
                "recall_at_fixed_precision": 0.5,
                "fixed_precision_target": 0.99,
                "precision_target_attained_on_validation": True,
            },
            "selected_model": {
                "pr_auc": 0.6,
                "recall": 0.8,
                "recall_at_fixed_precision": None,
                "fixed_precision_target": None,
                "precision_target_attained_on_validation": False,
                "brier": 0.1,
                "pr_auc_difference_vs_rule_ci": [0.1, 0.4],
            },
        },
        gate_diagnostics={"unseen_recall": 0.8, "leakage_warnings": []},
    )
    assert gate["criteria"]["comparable_precision_operating_point"] is False
    assert gate["criteria"]["recall_beats_rule_at_fixed_precision"] is False


def test_training_diagnostics_ignore_test_labels_and_values():
    frame = pd.DataFrame(
        {
            "time_split": ["train", "train", "validation", "validation", "test", "test"],
            "target": [0, 1, 0, 1, 0, 1],
            "feature": [0.1, 0.9, 0.2, 0.8, 0.3, 0.7],
        }
    )
    first = _training_validation_leakage_diagnostics(frame, ["feature"], {})
    changed_test = frame.copy()
    changed_test.loc[changed_test["time_split"] == "test", "target"] = [1, 0]
    changed_test.loc[changed_test["time_split"] == "test", "feature"] = [1000, -1000]
    second = _training_validation_leakage_diagnostics(changed_test, ["feature"], {})

    assert first == second


def test_facility_missingness_distinguishes_period_gaps_from_zero_values():
    observations = pd.DataFrame(
        [
            ("FAC-A", "ITEM-1", "2026-01-01", 0, 2),
            ("FAC-A", "ITEM-1", "2026-01-03", 5, ""),
            ("FAC-B", "ITEM-2", "2026-01-01", 8, 1),
            ("FAC-B", "ITEM-2", "2026-01-02", 7, 1),
        ],
        columns=[
            "facility_id", "item_id", "date", "stock_on_hand", "units_consumed"
        ],
    )
    original = observations.copy(deep=True)

    report = profile_inventory_missingness(observations, frequency="daily")

    assert report["facility_count"] == 2
    assert report["facility_item_pair_count"] == 2
    assert report["expected_periods_within_observed_ranges"] == 5
    assert report["missing_report_periods_within_observed_ranges"] == 1
    assert report["explicit_missing_values_by_column"]["stock_on_hand"] == 0
    assert report["explicit_missing_values_by_column"]["units_consumed"] == 1
    assert report["facility_summaries"][0] == {
        "facility_id": "FAC-A",
        "facility_item_pairs": 1,
        "observed_rows": 2,
        "expected_periods": 3,
        "missing_periods": 1,
    }
    pd.testing.assert_frame_equal(observations, original)


def test_tampered_feature_csv_fails_hash_validation(tmp_path):
    build_id = "v1-20261016T120000Z-" + "c" * 32
    directory = tmp_path / build_id
    directory.mkdir()
    feature_path = directory / "features.csv"
    pd.DataFrame(
        {
            "facility_id": ["F"],
            "item_id": ["I"],
            "date": ["2026-01-01"],
            "target": [0],
            "time_split": ["train"],
            "group_split": ["train"],
            "is_synthetic": [False],
            "feature": [1.0],
        }
    ).to_csv(feature_path, index=False)
    metadata = {
        "dataset_id": "upload",
        "dataset_hash": "a" * 64,
        "data_source": "uploaded",
        "build_id": build_id,
        "frequency": "daily",
        "horizon": 1,
        "label_mode": "new_stockout",
        "feature_list": ["feature"],
        "feature_availability": {},
        "feature_builder_state": {"feature_list": ["feature"]},
        "feature_lineage": {},
        "is_synthetic": False,
        "row_count": 1,
        "validation": {"valid": True},
        "split_boundaries": {},
        "leakage_diagnostics": {},
        "group_column": "facility_id",
        "feature_table_sha256": hashlib.sha256(feature_path.read_bytes()).hexdigest(),
        "feature_table_row_count": 1,
    }
    (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    feature_path.write_text(feature_path.read_text(encoding="utf-8").replace("1.0", "2.0"), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        _load_feature_table(directory)


def test_inconsistent_row_provenance_fails_validation(tmp_path):
    build_id = "v1-20261016T120000Z-" + "d" * 32
    directory = tmp_path / build_id
    directory.mkdir()
    feature_path = directory / "features.csv"
    pd.DataFrame(
        {
            "facility_id": ["F", "F"],
            "item_id": ["I", "I"],
            "date": ["2026-01-01", "2026-01-02"],
            "target": [0, 1],
            "time_split": ["train", "train"],
            "group_split": ["train", "train"],
            "is_synthetic": [False, True],
            "feature": [1.0, 2.0],
        }
    ).to_csv(feature_path, index=False)
    metadata = {
        "dataset_id": "upload",
        "dataset_hash": "a" * 64,
        "data_source": "uploaded",
        "build_id": build_id,
        "frequency": "daily",
        "horizon": 1,
        "label_mode": "new_stockout",
        "feature_list": ["feature"],
        "feature_availability": {},
        "feature_builder_state": {"feature_list": ["feature"]},
        "feature_lineage": {},
        "is_synthetic": False,
        "row_count": 2,
        "validation": {"valid": True},
        "split_boundaries": {},
        "leakage_diagnostics": {},
        "group_column": "facility_id",
        "feature_table_sha256": hashlib.sha256(feature_path.read_bytes()).hexdigest(),
        "feature_table_row_count": 2,
    }
    (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="is_synthetic"):
        _load_feature_table(directory)


def test_time_split_rejects_metadata_with_insufficient_purge_gap():
    rows = pd.DataFrame(
        {
            "facility_id": ["F"] * 100,
            "item_id": ["I"] * 100,
            "date": pd.date_range("2026-01-01", periods=100).strftime("%Y-%m-%d"),
            "target": np.ones(100, dtype=int),
        }
    )
    result = time_based_split(
        rows, horizon=4, frequency="daily", minimum_positives=0
    )
    rows["time_split"] = assign_time_splits(
        rows, result["boundaries"], frequency="daily"
    )
    boundaries = result["boundaries"].copy()
    boundaries["purged_before_test"] = boundaries["purged_before_test"][:-1]

    with pytest.raises(ValueError, match="purged_before_test|purge gap"):
        _validate_time_split_metadata(
            rows,
            {
                "frequency": "daily",
                "horizon": 4,
                "split_boundaries": {"time_based": boundaries},
            },
        )


def test_split_integrity_recomputation_does_not_depend_on_test_labels():
    rows = pd.DataFrame(
        {
            "facility_id": ["F"] * 100,
            "item_id": ["I"] * 100,
            "date": pd.date_range("2026-01-01", periods=100).strftime("%Y-%m-%d"),
            "target": np.ones(100, dtype=int),
        }
    )
    split = time_based_split(
        rows, horizon=4, frequency="daily", minimum_positives=0
    )
    rows["time_split"] = assign_time_splits(
        rows, split["boundaries"], frequency="daily"
    )
    metadata = {
        "frequency": "daily",
        "horizon": 4,
        "split_boundaries": {"time_based": split["boundaries"]},
    }

    assert _validate_time_split_metadata(rows, metadata)

    changed = rows.copy()
    test_rows = changed["time_split"] == "test"
    changed.loc[test_rows, "target"] = np.nan
    assert _validate_time_split_metadata(changed, metadata)


def test_monthly_time_split_purges_calendar_months_when_reports_are_missing():
    dates = pd.date_range("2020-01-31", periods=60, freq="ME").delete(14)
    rows = pd.DataFrame(
        {
            "facility_id": ["F"] * len(dates),
            "item_id": ["I"] * len(dates),
            "date": dates.strftime("%Y-%m-%d"),
            "target": np.zeros(len(dates), dtype=int),
        }
    )

    split = time_based_split(
        rows, horizon=2, frequency="monthly", minimum_positives=0
    )

    for key in ("purged_before_validation", "purged_before_test"):
        ordinals = [
            pd.Period(value, freq="M").ordinal
            for value in split["boundaries"][key]
        ]
        assert len(ordinals) >= 2
        assert np.diff(ordinals).tolist() == [1] * (len(ordinals) - 1)


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
            {"rule_baseline": {"pr_auc": 0.2, "recall": 0.1,
                               "recall_at_fixed_precision": 0.1, "fixed_precision_target": 0.5,
                               "precision_target_attained_on_validation": True},
             "selected_model": {"pr_auc": 0.8, "roc_auc": 0.8, "recall": 0.7,
                                "recall_at_fixed_precision": 0.7, "fixed_precision_target": 0.5,
                                "precision_target_attained_on_validation": True,
                                "brier": 0.1, "pr_auc_difference_vs_rule_ci": [0.1, 0.3]}},
            {"unseen_recall": 0.7, "leakage_warnings": []},
            "real_data",
        ),
        (
            False, True,
            {"rule_baseline": {"pr_auc": 0.2, "recall": 0.1,
                               "recall_at_fixed_precision": 0.1, "fixed_precision_target": 0.5,
                               "precision_target_attained_on_validation": True},
             "selected_model": {"pr_auc": 0.8, "roc_auc": 0.8, "recall": 0.7,
                                "recall_at_fixed_precision": 0.7, "fixed_precision_target": 0.5,
                                "precision_target_attained_on_validation": True,
                                "brier": 0.1, "pr_auc_difference_vs_rule_ci": [-0.1, 0.3]}},
            {"unseen_recall": 0.7, "leakage_warnings": []},
            "test_pr_auc_beats_rule_with_ci",
        ),
        (
            False, False,
            {"rule_baseline": {"pr_auc": 0.2, "recall": 0.8,
                               "recall_at_fixed_precision": 0.8, "fixed_precision_target": 0.5,
                               "precision_target_attained_on_validation": True},
             "selected_model": {"pr_auc": 0.8, "roc_auc": 0.8, "recall": 0.4,
                                "recall_at_fixed_precision": 0.4, "fixed_precision_target": 0.5,
                                "precision_target_attained_on_validation": True,
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
    ("status", "verified_hash", "synthetic", "expected"),
    [
        ("uploaded_unverified", "a" * 64, False, False),
        ("verified", "b" * 64, False, False),
        ("verified", "a" * 64, True, False),
        ("verified", "a" * 64, False, True),
    ],
)
def test_promotion_gate_requires_verified_matching_dataset_hash(
    status, verified_hash, synthetic, expected
):
    digest = "a" * 64
    result = evaluate_promotion_gate(
        is_synthetic=synthetic,
        time_based_split=True,
        provenance_status=status,
        dataset_hash=digest,
        verified_dataset_hash=verified_hash,
        test_metrics={
            "rule_baseline": {
                "pr_auc": 0.3,
                "recall": 0.5,
                "recall_at_fixed_precision": 0.5,
                "fixed_precision_target": 0.5,
                "precision_target_attained_on_validation": True,
            },
            "selected_model": {
                "pr_auc": 0.7,
                "recall": 0.8,
                "recall_at_fixed_precision": 0.8,
                "fixed_precision_target": 0.5,
                "precision_target_attained_on_validation": True,
                "brier": 0.1,
                "pr_auc_difference_vs_rule_ci": [0.1, 0.3],
            },
        },
        gate_diagnostics={
            "unseen_recall": 0.75,
            "history_period_count": 36,
            "minimum_history_periods": 24,
            "positive_counts_per_split": {"train": 2, "validation": 2, "test": 2},
            "minimum_positives_per_split": 1,
            "distinct_facilities": 12,
            "minimum_facilities": 12,
            "leakage_warnings": [],
        },
    )

    assert result["criteria"]["verified_provenance"] is expected
    assert result["model_validated"] is expected


@pytest.mark.parametrize(
    "criterion",
    [
        "real_data",
        "verified_provenance",
        "time_based_split",
        "test_pr_auc_beats_rule_with_ci",
        "recall_beats_rule_at_fixed_precision",
        "comparable_precision_operating_point",
        "calibration_within_limit",
        "unseen_facility_within_tolerance",
        "no_phase3_leakage_warnings",
        "minimum_history_and_support",
    ],
)
def test_promotion_gate_rejects_each_failed_criterion(criterion):
    test_metrics = {
        "rule_baseline": {
            "pr_auc": 0.3, "recall": 0.4,
            "recall_at_fixed_precision": 0.4, "fixed_precision_target": 0.5,
            "precision_target_attained_on_validation": True,
        },
        "selected_model": {
            "pr_auc": 0.6, "roc_auc": 0.7, "recall": 0.8, "brier": 0.1,
            "recall_at_fixed_precision": 0.8, "fixed_precision_target": 0.5,
            "precision_target_attained_on_validation": True,
            "pr_auc_difference_vs_rule_ci": [0.1, 0.4],
        },
    }
    diagnostics = {
        "unseen_recall": 0.8,
        "leakage_warnings": [],
        "history_period_count": 36,
        "minimum_history_periods": 24,
        "positive_counts_per_split": {
            "train": 30, "validation": 30, "test": 30,
        },
        "minimum_positives_per_split": 30,
        "distinct_facilities": 24,
        "minimum_facilities": 12,
    }
    synthetic = False
    time_split = True
    if criterion == "real_data":
        synthetic = True
    elif criterion == "time_based_split":
        time_split = False
    elif criterion == "test_pr_auc_beats_rule_with_ci":
        test_metrics["selected_model"]["pr_auc_difference_vs_rule_ci"] = [-0.1, 0.2]
    elif criterion == "recall_beats_rule_at_fixed_precision":
        test_metrics["selected_model"]["recall_at_fixed_precision"] = 0.2
    elif criterion == "comparable_precision_operating_point":
        test_metrics["selected_model"]["precision_target_attained_on_validation"] = False
    elif criterion == "calibration_within_limit":
        test_metrics["selected_model"]["brier"] = 0.9
    elif criterion == "unseen_facility_within_tolerance":
        diagnostics["unseen_recall"] = 0.1
    elif criterion == "no_phase3_leakage_warnings":
        diagnostics["leakage_warnings"] = ["future stock"]
    elif criterion == "minimum_history_and_support":
        diagnostics["history_period_count"] = 23

    result = evaluate_promotion_gate(
        is_synthetic=synthetic,
        time_based_split=time_split,
        test_metrics=test_metrics,
        gate_diagnostics=diagnostics,
    )

    assert criterion in result["failed_criteria"]


def _build_synthetic_feature_table(uploads_root: Path, output_root: Path) -> str:
    built = prepare_synthetic_feature_dataset(
        data_root=uploads_root,
        feature_root=output_root,
    )
    metadata = json.loads((built / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["data_source"] == "synthetic_generated"
    return metadata["build_id"]


def test_synthetic_end_to_end_training_is_unvalidated_and_versioned(tmp_path):
    feature_root = tmp_path / "features"
    upload_root = tmp_path / "uploads"
    build_id = _build_synthetic_feature_table(upload_root, feature_root)
    feature_metadata = json.loads(
        next(feature_root.rglob("metadata.json")).read_text(encoding="utf-8")
    )
    assert feature_metadata["provenance_status"] == "synthetic"
    assert feature_metadata["verification"] is None
    assert feature_metadata["verified_dataset_hash"] is None
    output_root = tmp_path / "models"

    command = [
        sys.executable, "-m", "ml.train", build_id,
        "--feature-root", str(feature_root),
        "--model-root", str(output_root),
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
    assert metadata["provenance_status"] == "synthetic"
    assert metadata["verified_dataset_hash"] is None
    assert metadata["model_validated"] is False
    assert metadata["feature_table_row_count"] == metadata["row_count"]
    assert len(metadata["feature_table_sha256"]) == 64
    assert metadata["source_missingness"]["missing_report_periods_within_observed_ranges"] == 0
    assert metadata["source_missingness"]["facility_count"] == 48
    assert metadata["evaluation_integrity"] == {
        "feature_table_hash_verified": True,
        "feature_table_row_count_verified": True,
        "build_id_verified": True,
        "row_provenance_verified": True,
        "time_based_split_verified": True,
        "grouped_split_verified": True,
        "test_label_diagnostics_used_before_final_pass": False,
    }
    assert metadata["test_access_count"] == 1
    assert metadata["test_metrics"]["pr_auc"] is not None
    assert metadata["test_metrics"]["roc_auc"] is not None
    assert metadata["test_metrics"]["pr_auc"] > metadata["all_test_metrics"]["rule_baseline"]["pr_auc"]
    assert metadata["all_test_metrics"]["logistic_regression"]["pr_auc_difference_vs_rule_ci"]
    assert metadata["all_test_metrics"]["rule_baseline"]["cluster_bootstrap_95_ci"]["pr_auc"]
    assert metadata["all_test_metrics"]["persistence_baseline"]["cluster_bootstrap_95_ci"]["pr_auc"]
    assert metadata["feature_builder_state"]["feature_list"] == metadata["feature_list"]
    assert metadata["test_metrics"]["recall_at_fixed_precision"] == metadata["test_metrics"]["recall"]
    assert (
        metadata["test_metrics"]["fixed_precision_target"]
        == metadata["all_test_metrics"]["rule_baseline"]["fixed_precision_target"]
        == 0.5
    )
    assert metadata["unseen_group"]["results"]["status"] == "computed"
    assert {
        "time_based_split", "test_metrics", "training_date_range", "data_hash",
        "feature_list", "horizon_days", "data_frequency", "is_synthetic",
        "horizon_periods",
        "threshold", "gate_results", "model_validated", "library_versions",
        "random_seed", "git_commit",
    }.issubset(metadata)
    assert report["gate_results"]["model_validated"] is False
    assert metadata["data_frequency"] == "monthly"
    assert metadata["horizon_periods"] == 1
    assert report["effective_sample_size"]["test"]["distinct_facilities"] >= 12
    assert metadata["rule_cover_thresholds"] == {
        "critical_below": 0.25,
        "moderate_through": 0.5,
        "unit": "months",
    }
    assert metadata["all_test_metrics"]["rule_baseline"]["cluster_bootstrap_95_ci"]["valid_resamples"] >= 1000
    assert (artifact / "model.joblib").is_file()
    assert (artifact / "calibrators.joblib").is_file()
    assert (artifact / "feature_builder_state.json").is_file()
    assert (artifact / "evaluation_report.md").read_text(encoding="utf-8").startswith(
        "# SYNTHETIC - not evidence of real-world performance"
    )


def test_real_upload_training_rejects_synthetic_registered_dataset(monkeypatch, tmp_path):
    source = generate_synthetic_supply_history(
        facilities=2, periods=24, seed=17, frequency="monthly"
    )
    dataset_id = "v1-20261016T120000Z-" + "c" * 32
    upload_dir = tmp_path / "v1" / dataset_id
    upload_dir.mkdir(parents=True)
    data_path = upload_dir / "data.csv"
    source.to_csv(data_path, index=False)
    registry = {
        "dataset_id": dataset_id,
        "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "row_count": len(source),
        "is_synthetic": True,
        "data_source": "uploaded",
    }
    (upload_dir / "metadata.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(
        train_uploaded_dataset,
        "build_dataset",
        lambda *args, **kwargs: pytest.fail("Synthetic upload must not reach feature building."),
    )

    with pytest.raises(ValueError, match="is_synthetic=false"):
        train_uploaded_dataset.train_uploaded_candidate(dataset_id, uploads_root=tmp_path)


def test_real_upload_training_builds_and_trains_registered_dataset(monkeypatch, tmp_path):
    dataset_id = "v1-20261016T120000Z-" + "d" * 32
    registry = {
        "dataset_id": dataset_id,
        "data_source": "uploaded",
        "is_synthetic": False,
    }
    feature_dir = tmp_path / "features" / "build"
    feature_dir.mkdir(parents=True)
    (feature_dir / "metadata.json").write_text(
        json.dumps({"build_id": "v1-feature-build"}),
        encoding="utf-8",
    )
    artifact_dir = tmp_path / "models" / "candidate"
    calls = {}

    def build_dataset(actual_id, **kwargs):
        calls["build"] = (actual_id, kwargs)
        return feature_dir

    def train_feature_dataset(actual_id, **kwargs):
        calls["train"] = (actual_id, kwargs)
        return artifact_dir

    monkeypatch.setattr(
        train_uploaded_dataset,
        "_load_registered_dataset",
        lambda actual_id, uploads_root: (pd.DataFrame(), registry, "a" * 64),
    )
    monkeypatch.setattr(train_uploaded_dataset, "build_dataset", build_dataset)
    monkeypatch.setattr(
        train_uploaded_dataset,
        "train_feature_dataset",
        train_feature_dataset,
    )

    result = train_uploaded_dataset.train_uploaded_candidate(
        dataset_id,
        uploads_root=tmp_path / "uploads",
        feature_root=tmp_path / "features",
        model_root=tmp_path / "models",
        minimum_history_periods=30,
        bootstrap_repetitions=1200,
    )

    assert result == artifact_dir
    assert calls["build"] == (
        dataset_id,
        {"uploads_root": tmp_path / "uploads", "output_root": tmp_path / "features"},
    )
    assert calls["train"] == (
        "v1-feature-build",
        {
            "feature_root": tmp_path / "features",
            "model_root": tmp_path / "models",
            "minimum_history_periods": 30,
            "bootstrap_repetitions": 1200,
        },
    )
