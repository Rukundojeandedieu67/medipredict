from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import platform
import re
import subprocess
import sys
import uuid
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.inspection import permutation_importance
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from backend.app.config import settings
from backend.app.provenance import ProvenanceError, resolve_provenance
from .leakage import target_leakage_diagnostics
from .promote import evaluate_promotion_gate
from .splits import assign_time_splits, grouped_unseen_split, time_based_split

LOGGER = logging.getLogger("ml.train")
FEATURE_ROOT = Path(__file__).resolve().parent / "artifacts" / "feature_tables"
MODEL_ROOT = Path(__file__).resolve().parent / "models"
DEFAULT_SEED = 20261016
FEATURE_BUILD_ID_PATTERN = re.compile(r"^v1-\d{8}T\d{6}Z-[0-9a-f]{32}$")


def _log_prefix(is_synthetic: bool) -> str:
    return (
        "SYNTHETIC - not evidence of real-world performance | "
        if is_synthetic else ""
    )


def _log(message: str, *, is_synthetic: bool) -> None:
    if is_synthetic:
        print(_log_prefix(True) + message, file=sys.stderr, flush=True)
    else:
        LOGGER.warning(message)


def _resolve_feature_table(identifier: str, root: Path) -> Path:
    if not FEATURE_BUILD_ID_PATTERN.fullmatch(identifier):
        raise ValueError("Feature dataset ID must be a build ID emitted by ml.build_dataset.")
    matches = [
        path.parent
        for path in root.rglob("metadata.json")
        if path.parent.name == identifier
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Feature dataset ID '{identifier}' resolved to {len(matches)} tables; "
            "provide an unambiguous build ID."
        )
    return matches[0]


def _create_artifact_directory(model_root: Path, version: str) -> Path:
    destination = model_root / version
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def _load_feature_table(directory: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    metadata_path = directory / "metadata.json"
    features_path = directory / "features.csv"
    if not metadata_path.is_file() or not features_path.is_file():
        raise FileNotFoundError("Feature dataset must contain metadata.json and features.csv.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    required = (
        "dataset_id", "dataset_hash", "data_source", "build_id", "frequency",
        "horizon", "label_mode", "feature_list", "feature_availability",
        "feature_builder_state", "feature_lineage", "is_synthetic", "validation",
        "split_boundaries", "leakage_diagnostics", "feature_table_sha256",
        "feature_table_row_count", "row_count", "group_column",
    )
    missing = [field for field in required if field not in metadata]
    if missing:
        raise ValueError(f"Feature dataset metadata is missing: {', '.join(missing)}")
    if metadata.get("validation", {}).get("valid") is not True:
        raise ValueError("Feature dataset failed validation.")
    if metadata["data_source"] not in ("uploaded", "synthetic_generated"):
        raise ValueError("Feature dataset must originate from a supported training pipeline.")
    if metadata["build_id"] != directory.name:
        raise ValueError("Feature build ID does not match the feature-table directory.")
    if metadata["frequency"] not in ("daily", "monthly") or int(metadata["horizon"]) < 1:
        raise ValueError("Feature dataset has invalid frequency or horizon metadata.")
    if metadata["frequency"] == "monthly" and int(metadata["horizon"]) not in (1, 2):
        raise ValueError("Monthly feature dataset horizon must be one or two periods.")
    if metadata["feature_builder_state"].get("feature_list") != metadata["feature_list"]:
        raise ValueError("FeatureBuilder state does not match the feature dataset schema.")
    if not isinstance(metadata["is_synthetic"], bool):
        raise ValueError("Feature dataset is missing a valid is_synthetic metadata flag.")
    if metadata["data_source"] == "synthetic_generated" and not metadata["is_synthetic"]:
        raise ValueError("Generated synthetic feature datasets must be marked is_synthetic=true.")
    frame = pd.read_csv(features_path)
    required_columns = {
        "target", "time_split", "group_split", "facility_id", "date", "is_synthetic"
    }
    absent = sorted(required_columns.difference(frame.columns))
    if absent:
        raise ValueError(f"Feature table is missing required columns: {', '.join(absent)}")
    actual_hash = hashlib.sha256(features_path.read_bytes()).hexdigest()
    if actual_hash != metadata["feature_table_sha256"]:
        raise ValueError("Feature table SHA-256 does not match its build metadata.")
    if len(frame) != metadata["feature_table_row_count"]:
        raise ValueError("Feature table row count does not match its build metadata.")
    if len(frame) != metadata["row_count"]:
        raise ValueError("Feature table row count does not match its recorded dataset row count.")
    if not isinstance(metadata["dataset_hash"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", metadata["dataset_hash"]
    ):
        raise ValueError("Feature metadata has no valid registered-dataset SHA-256.")
    synthetic_flags = frame["is_synthetic"].map(_parse_synthetic_flag)
    if synthetic_flags.isna().any() or not synthetic_flags.eq(metadata["is_synthetic"]).all():
        raise ValueError("Feature-table is_synthetic values do not match dataset metadata.")
    return frame, metadata


def _parse_synthetic_flag(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _current_dataset_provenance(
    metadata: dict[str, Any],
) -> tuple[str, dict[str, Any] | None, str | None]:
    if metadata.get("is_synthetic") is True:
        return "synthetic", None, None
    recorded_status = metadata.get("provenance_status")
    recorded_verification = metadata.get("verification")
    dataset_hash = metadata.get("dataset_hash")
    if (
        recorded_status == "verified"
        and isinstance(recorded_verification, dict)
        and recorded_verification.get("dataset_sha256") == dataset_hash
        and isinstance(dataset_hash, str)
    ):
        return "verified", recorded_verification, dataset_hash
    if recorded_status == "uploaded_unverified":
        return "uploaded_unverified", None, None
    dataset_id = metadata.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id:
        return "uploaded_unverified", None, None
    try:
        current = resolve_provenance(dataset_id, settings.uploads_path)
    except (FileNotFoundError, OSError, ProvenanceError) as exc:
        LOGGER.warning(
            "Source dataset provenance could not be rechecked for training: %s", exc
        )
        return "uploaded_unverified", None, None
    verification = current.get("verification")
    if (
        current.get("provenance_status") == "verified"
        and isinstance(verification, dict)
        and verification.get("dataset_sha256") == metadata.get("dataset_hash")
    ):
        return "verified", verification, verification["dataset_sha256"]
    return str(current.get("provenance_status", "uploaded_unverified")), None, None


def _validate_training_history(
    frame: pd.DataFrame,
    *,
    frequency: str,
    minimum_history_periods: int,
    minimum_facilities: int,
) -> tuple[int, int, int]:
    history_period_count = int(
        pd.to_datetime(frame["date"], format="%Y-%m-%d")
        .dt.to_period("M" if frequency == "monthly" else "D")
        .nunique()
    )
    required_history = max(24, minimum_history_periods) if frequency == "monthly" else 1
    if history_period_count < required_history:
        unit = "months" if frequency == "monthly" else "days"
        raise ValueError(
            f"Feature dataset has {history_period_count} distinct {unit}; "
            f"at least {required_history} are required."
        )
    distinct_facilities = int(frame["facility_id"].nunique())
    if distinct_facilities < minimum_facilities:
        raise ValueError(
            f"Feature dataset has {distinct_facilities} distinct facilities; "
            f"at least {minimum_facilities} are required."
        )
    return history_period_count, required_history, distinct_facilities


def _validate_split_positives(
    split_name: str,
    frame: pd.DataFrame,
    *,
    minimum_positives: int,
    require_both_classes: bool = True,
) -> int:
    positives = int(pd.to_numeric(frame["target"], errors="raise").sum())
    if positives < minimum_positives:
        raise ValueError(
            f"{split_name} split has {positives} positives; at least "
            f"{minimum_positives} are required."
        )
    if require_both_classes and frame["target"].nunique() < 2:
        raise ValueError(
            f"{split_name} split has only one label class; model selection and "
            "calibration require both positive and negative labels."
        )
    return positives


def _observation_keys(frame: pd.DataFrame) -> list[tuple[str, str, pd.Timestamp]]:
    return [
        (str(row.facility_id), str(row.item_id), pd.Timestamp(row.date))
        for row in frame[["facility_id", "item_id", "date"]].itertuples(index=False)
    ]


def _assignment_map(split_result: dict[str, Any]) -> dict[tuple[str, str, pd.Timestamp], str]:
    assignments: dict[tuple[str, str, pd.Timestamp], str] = {}
    for split_name, split_frame in split_result["splits"].items():
        for key in _observation_keys(split_frame):
            assignments[key] = split_name
    return assignments


def _validate_time_split_metadata(
    frame: pd.DataFrame,
    metadata: dict[str, Any],
) -> bool:
    frequency = metadata["frequency"]
    horizon = int(metadata["horizon"])
    split_input = frame[["facility_id", "item_id", "date"]].copy()
    split_input["target"] = 0
    recomputed = time_based_split(
        split_input,
        horizon=horizon,
        frequency=frequency,
        minimum_positives=0,
    )
    expected_values = assign_time_splits(
        frame, recomputed["boundaries"], frequency=frequency
    ).tolist()
    expected = [
        None if pd.isna(value) or str(value).strip() == "" else str(value)
        for value in expected_values
    ]
    actual_values = frame["time_split"]
    actual = [
        None if pd.isna(value) or str(value).strip() == "" else str(value)
        for value in actual_values
    ]
    if actual != expected:
        raise ValueError("Stored time-split assignments do not match the recomputed split.")

    expected_boundaries = recomputed["boundaries"]
    stored_boundaries = metadata["split_boundaries"].get("time_based")
    if not isinstance(stored_boundaries, dict):
        raise ValueError("Feature metadata is missing time-based split boundaries.")
    structural_keys = (
        "train_period_start", "train_period_end",
        "validation_period_start", "validation_period_end",
        "test_period_start", "test_period_end", "purge_gap_periods",
        "purged_before_validation", "purged_before_test", "frequency", "horizon",
    )
    for key in structural_keys:
        if stored_boundaries.get(key) != expected_boundaries.get(key):
            raise ValueError(f"Stored time-split boundary '{key}' failed integrity validation.")
    if len(stored_boundaries.get("purged_before_validation", [])) < horizon:
        raise ValueError("Train/validation purge gap is shorter than the label horizon.")
    if len(stored_boundaries.get("purged_before_test", [])) < horizon:
        raise ValueError("Validation/test purge gap is shorter than the label horizon.")
    return True


def _validate_group_split_metadata(
    frame: pd.DataFrame,
    metadata: dict[str, Any],
) -> None:
    group_column = metadata.get("group_column")
    if group_column not in ("facility_id", "district"):
        raise ValueError("Feature metadata has an invalid unseen-group split column.")
    split_columns = list(dict.fromkeys(["facility_id", "item_id", "date", group_column]))
    split_input = frame[split_columns].copy()
    split_input["target"] = 0
    recomputed = grouped_unseen_split(
        split_input,
        group_column=group_column,
        minimum_positives=0,
    )
    expected = _assignment_map(recomputed)
    actual_values = frame["group_split"]
    actual = [
        None if pd.isna(value) or str(value).strip() == "" else str(value)
        for value in actual_values
    ]
    if actual != [expected.get(key) for key in _observation_keys(frame)]:
        raise ValueError("Stored unseen-group assignments do not match the recomputed split.")

    stored = metadata["split_boundaries"].get("unseen_group")
    expected_boundaries = recomputed["boundaries"]
    if not isinstance(stored, dict):
        raise ValueError("Feature metadata is missing unseen-group split boundaries.")
    for key in ("group_column", "train_groups", "test_groups"):
        if stored.get(key) != expected_boundaries.get(key):
            raise ValueError(f"Stored unseen-group boundary '{key}' failed integrity validation.")


def _validate_labeled_split_summary(
    split_name: str,
    frame: pd.DataFrame,
    stored: dict[str, Any],
) -> None:
    dates = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="raise")
    positives = int(pd.to_numeric(frame["target"], errors="raise").sum())
    actual = {
        "row_count": len(frame),
        "labeled_row_count": len(frame),
        "positive_count": positives,
        "label_prevalence": positives / len(frame) if len(frame) else None,
        "start": dates.min().date().isoformat() if len(dates) else None,
        "end": dates.max().date().isoformat() if len(dates) else None,
    }
    for key, value in actual.items():
        expected = stored.get(key)
        if key == "label_prevalence" and value is not None and expected is not None:
            if not np.isclose(float(expected), value):
                raise ValueError(f"Stored {split_name} label prevalence failed integrity validation.")
        elif expected != value:
            raise ValueError(f"Stored {split_name} split summary failed integrity validation.")


def _apply_calibrator(calibrator: Any | None, scores: np.ndarray) -> np.ndarray:
    if calibrator is None:
        return scores.copy()
    if isinstance(calibrator, IsotonicRegression):
        return np.asarray(calibrator.predict(scores), dtype=float)
    return np.asarray(
        calibrator.predict_proba(scores.reshape(-1, 1))[:, 1],
        dtype=float,
    )


def _validation_policy(
    y_validation: np.ndarray,
    validation_scores: np.ndarray,
    target: float,
    *,
    threshold_objective: str = "precision",
) -> tuple[np.ndarray, Any | None, float, dict[str, Any], dict[str, Any]]:
    calibrator = None
    positives = int(np.sum(y_validation == 1))
    negatives = int(np.sum(y_validation == 0))
    if positives >= 20 and negatives >= 20:
        calibrator = IsotonicRegression(out_of_bounds="clip").fit(
            validation_scores, y_validation
        )
        calibrated_scores = _apply_calibrator(calibrator, validation_scores)
        calibration = {
            "method": "isotonic",
            "fit_data": "validation predictions and labels only",
            "brier_before": float(brier_score_loss(y_validation, validation_scores)),
            "brier_after": float(brier_score_loss(y_validation, calibrated_scores)),
            "calibrator": calibrator,
        }
    elif positives >= 2 and negatives >= 2:
        calibrator = LogisticRegression(max_iter=1000, random_state=DEFAULT_SEED).fit(
            validation_scores.reshape(-1, 1), y_validation
        )
        calibrated_scores = _apply_calibrator(calibrator, validation_scores)
        calibration = {
            "method": "platt",
            "fit_data": "validation predictions and labels only",
            "reason": (
                "Platt scaling used because validation has fewer than 20 "
                "positive or negative examples for isotonic calibration."
            ),
            "brier_before": float(brier_score_loss(y_validation, validation_scores)),
            "brier_after": float(brier_score_loss(y_validation, calibrated_scores)),
            "calibrator": calibrator,
        }
    else:
        calibrated_scores = validation_scores.copy()
        calibration = {
            "method": None,
            "reason": (
                "Calibration not computed: validation needs at least two "
                "examples from each class."
            ),
            "brier_before": float(brier_score_loss(y_validation, validation_scores)),
            "brier_after": None,
            "calibrator": None,
        }
    threshold, selection = _select_operating_threshold(
        y_validation,
        calibrated_scores,
        target,
        threshold_objective,
    )
    return calibrated_scores, calibrator, threshold, selection, calibration


def _rule_scores(
    frame: pd.DataFrame,
    frequency: str,
    *,
    critical_limit: float | None = None,
    moderate_limit: float | None = None,
) -> np.ndarray:
    cover_column = "days_of_cover" if frequency == "daily" else "months_of_stock"
    if cover_column not in frame:
        raise ValueError(f"Rule baseline requires feature '{cover_column}'.")
    cover = pd.to_numeric(frame[cover_column], errors="coerce").to_numpy(dtype=float)
    if critical_limit is None or moderate_limit is None:
        defaults = (7.0, 14.0) if frequency == "daily" else (0.25, 0.5)
        critical_limit = defaults[0] if critical_limit is None else critical_limit
        moderate_limit = defaults[1] if moderate_limit is None else moderate_limit
    if critical_limit >= moderate_limit:
        raise ValueError("The critical rule threshold must be lower than the moderate threshold.")
    scores = np.full(len(cover), -0.5, dtype=float)
    finite = np.isfinite(cover)
    scores[finite & (cover < critical_limit)] = 1.0
    scores[finite & (cover >= critical_limit) & (cover <= moderate_limit)] = 0.5
    scores[finite & (cover > moderate_limit)] = 0.0
    return scores


class TestSetAccessGuard:
    """Expose test rows exactly once, only after all validation decisions."""

    __test__ = False

    def __init__(self, frame_or_loader: pd.DataFrame | Any):
        self._frame_or_loader = frame_or_loader
        self.access_count = 0

    def evaluate_once(self) -> pd.DataFrame:
        if self.access_count:
            raise RuntimeError("Test set may be accessed only once.")
        self.access_count += 1
        if callable(self._frame_or_loader):
            return self._frame_or_loader()
        return self._frame_or_loader.copy()


def _feature_columns(frame: pd.DataFrame, metadata: dict[str, Any]) -> list[str]:
    columns = [name for name in metadata["feature_list"] if name in frame.columns]
    missing = sorted(set(metadata["feature_list"]).difference(frame.columns))
    if missing:
        raise ValueError(
            "Feature table is missing declared feature columns: "
            + ", ".join(missing)
        )
    if not columns:
        raise ValueError("No declared Phase 3 features are present in the feature table.")
    return columns


def _training_validation_leakage_diagnostics(
    frame: pd.DataFrame,
    feature_columns: list[str],
    feature_lineage: dict[str, dict[str, object]],
) -> dict[str, Any]:
    scoped = frame.loc[frame["time_split"].isin(("train", "validation"))]
    scoped = scoped.loc[scoped["target"].notna()]
    return target_leakage_diagnostics(
        scoped[feature_columns],
        scoped[["target"]],
        feature_lineage=feature_lineage,
    )


def _split_xy(
    frame: pd.DataFrame,
    features: list[str],
) -> tuple[pd.DataFrame, np.ndarray]:
    x = frame.loc[:, features].copy()
    for column in x.columns:
        if pd.api.types.is_bool_dtype(x[column]):
            x[column] = x[column].astype("float64")
        elif pd.api.types.is_numeric_dtype(x[column]):
            x[column] = pd.to_numeric(x[column], errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            )
    y = pd.to_numeric(frame["target"], errors="raise").astype(int).to_numpy()
    return x, y


def _preprocessors(x_train: pd.DataFrame) -> tuple[ColumnTransformer, ColumnTransformer]:
    numeric = [
        column for column in x_train
        if (
            pd.api.types.is_numeric_dtype(x_train[column])
            or pd.api.types.is_bool_dtype(x_train[column])
        )
        and x_train[column].nunique(dropna=True) > 1
    ]
    categorical = [
        column for column in x_train
        if column not in numeric and x_train[column].nunique(dropna=True) > 1
    ]
    if not numeric and not categorical:
        raise ValueError("No non-constant training features are available.")
    numeric_logistic = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
        ]
    )
    numeric_tree = "passthrough"
    category_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    logistic = ColumnTransformer(
        [("numeric", numeric_logistic, numeric), ("categorical", category_pipeline, categorical)],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    tree = ColumnTransformer(
        [("numeric", numeric_tree, numeric), ("categorical", category_pipeline, categorical)],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    return logistic, tree


def _probabilities(model: Any, x: pd.DataFrame) -> np.ndarray:
    probabilities = np.asarray(model.predict_proba(x), dtype=float)
    classes = list(model.classes_)
    positive_index = classes.index(1)
    return probabilities[:, positive_index]


def _best_validation_parameters(
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    x_validation: pd.DataFrame,
    y_validation: np.ndarray,
    *,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    logistic_prep, tree_prep = _preprocessors(x_train)
    logistic_candidates: list[tuple[float, dict[str, Any], Any]] = []
    for c_value in (0.1, 1.0, 10.0):
        estimator = Pipeline(
            [
                ("preprocess", sklearn.base.clone(logistic_prep)),
                ("classifier", LogisticRegression(C=c_value, class_weight="balanced", max_iter=1000, random_state=seed)),
            ]
        )
        estimator.fit(x_train, y_train)
        score = _safe_pr_auc(y_validation, _probabilities(estimator, x_validation))
        logistic_candidates.append((score, {"C": c_value}, estimator))
    tree_candidates: list[tuple[float, dict[str, Any], Any]] = []
    for leaf in (10, 30):
        estimator = Pipeline(
            [
                ("preprocess", sklearn.base.clone(tree_prep)),
                ("classifier", HistGradientBoostingClassifier(
                    max_iter=100, learning_rate=0.08, max_leaf_nodes=15,
                    l2_regularization=1.0, min_samples_leaf=leaf,
                    class_weight="balanced", random_state=seed,
                )),
            ]
        )
        estimator.fit(x_train, y_train)
        score = _safe_pr_auc(y_validation, _probabilities(estimator, x_validation))
        tree_candidates.append((score, {"min_samples_leaf": leaf}, estimator))
    logistic_best = max(
        logistic_candidates,
        key=lambda item: float("-inf") if item[0] is None else item[0],
    )
    tree_best = max(
        tree_candidates,
        key=lambda item: float("-inf") if item[0] is None else item[0],
    )
    return (
        {"logistic_regression": logistic_best[1], "hist_gradient_boosting": tree_best[1]},
        {"logistic_regression": logistic_best[2], "hist_gradient_boosting": tree_best[2]},
        {"logistic_regression": logistic_best[0], "hist_gradient_boosting": tree_best[0]},
    )


def _fit_group_model(
    name: str,
    parameters: dict[str, Any],
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    *,
    seed: int,
) -> Any:
    logistic_prep, tree_prep = _preprocessors(x_train)
    if name == "logistic_regression":
        estimator = Pipeline(
            [
                ("preprocess", logistic_prep),
                ("classifier", LogisticRegression(
                    C=float(parameters["C"]), class_weight="balanced",
                    max_iter=1000, random_state=seed,
                )),
            ]
        )
    else:
        estimator = Pipeline(
            [
                ("preprocess", tree_prep),
                ("classifier", HistGradientBoostingClassifier(
                    max_iter=100, learning_rate=0.08, max_leaf_nodes=15,
                    l2_regularization=1.0,
                    min_samples_leaf=int(parameters["min_samples_leaf"]),
                    class_weight="balanced", random_state=seed,
                )),
            ]
        )
    return estimator.fit(x_train, y_train)


def _safe_pr_auc(y: np.ndarray, scores: np.ndarray) -> float | None:
    return (
        float(average_precision_score(y, scores))
        if len(np.unique(y)) > 1
        else None
    )


def _threshold_for_precision(
    y: np.ndarray,
    scores: np.ndarray,
    precision_target: float,
) -> tuple[float, dict[str, Any]]:
    precision, recall, thresholds = precision_recall_curve(y, scores)
    candidates = [
        (float(recall[index]), float(thresholds[index]), float(precision[index]))
        for index in range(len(thresholds))
        if precision[index] >= precision_target
    ]
    if candidates:
        selected = max(candidates, key=lambda item: (item[0], item[2], -item[1]))
        return selected[1], {
            "selection": "maximum validation recall meeting precision target",
            "precision_target": precision_target,
            "precision_target_attained": True,
            "validation_precision": selected[2],
            "validation_recall": selected[0],
            "validation_f1": float(
                f1_score(y, scores >= selected[1], zero_division=0)
            ),
        }
    if len(thresholds):
        f1_values = [
            f1_score(y, scores >= threshold, zero_division=0)
            for threshold in thresholds
        ]
        index = int(np.argmax(f1_values))
        return float(thresholds[index]), {
            "selection": "maximum validation F1; precision target was unattainable",
            "precision_target": precision_target,
            "precision_target_attained": False,
            "validation_precision": float(precision[index]),
            "validation_recall": float(recall[index]),
            "validation_f1": float(f1_values[index]),
        }
    return 0.5, {
        "selection": "fixed default; validation scores had no thresholds",
        "precision_target": precision_target,
        "precision_target_attained": False,
        "validation_precision": None,
        "validation_recall": None,
        "validation_f1": None,
    }


def _threshold_for_recall(
    y: np.ndarray,
    scores: np.ndarray,
    recall_target: float,
) -> tuple[float, dict[str, Any]]:
    precision, recall, thresholds = precision_recall_curve(y, scores)
    candidates = [
        (float(precision[index]), float(recall[index]), float(thresholds[index]))
        for index in range(len(thresholds))
        if recall[index] >= recall_target
    ]
    if candidates:
        selected = max(candidates, key=lambda item: (item[0], item[1], item[2]))
        return selected[2], {
            "selection": "maximum validation precision meeting recall target",
            "recall_target": recall_target,
            "operating_target_attained": True,
            "precision_target_attained": False,
            "validation_precision": selected[0],
            "validation_recall": selected[1],
            "validation_f1": float(
                f1_score(y, scores >= selected[2], zero_division=0)
            ),
        }
    if len(thresholds):
        f1_values = [
            f1_score(y, scores >= threshold, zero_division=0)
            for threshold in thresholds
        ]
        index = int(np.argmax(f1_values))
        return float(thresholds[index]), {
            "selection": "maximum validation F1; recall target was unattainable",
            "recall_target": recall_target,
            "operating_target_attained": False,
            "precision_target_attained": False,
            "validation_precision": float(precision[index]),
            "validation_recall": float(recall[index]),
            "validation_f1": float(f1_values[index]),
        }
    return 0.5, {
        "selection": "fixed default; validation scores had no thresholds",
        "recall_target": recall_target,
        "operating_target_attained": False,
        "precision_target_attained": False,
        "validation_precision": None,
        "validation_recall": None,
        "validation_f1": None,
    }


def _select_operating_threshold(
    y: np.ndarray,
    scores: np.ndarray,
    target: float,
    objective: str,
) -> tuple[float, dict[str, Any]]:
    if objective == "precision":
        threshold, selection = _threshold_for_precision(y, scores, target)
        selection["operating_target_attained"] = selection[
            "precision_target_attained"
        ]
        return threshold, selection
    if objective == "recall":
        return _threshold_for_recall(y, scores, target)
    raise ValueError("threshold objective must be 'precision' or 'recall'")


def _metric_summary(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    predictions = scores >= threshold
    return {
        "pr_auc": _safe_pr_auc(y, scores),
        "roc_auc": float(roc_auc_score(y, scores)) if len(np.unique(y)) > 1 else None,
        "brier": float(brier_score_loss(y, np.clip(scores, 0, 1))),
        "precision": float(precision_score(y, predictions, zero_division=0)),
        "recall": float(recall_score(y, predictions, zero_division=0)),
        "f1": float(f1_score(y, predictions, zero_division=0)),
        "label_prevalence": float(np.mean(y)) if len(y) else None,
        "rows": int(len(y)),
        "positives": int(y.sum()),
        "threshold": float(threshold),
        "not_computed_reasons": (
            {} if len(np.unique(y)) > 1 else {
                "pr_auc": "requires both positive and negative labels",
                "roc_auc": "requires both positive and negative labels",
            }
        ),
    }


def _cluster_bootstrap_pr_difference(
    frame: pd.DataFrame,
    *,
    y: np.ndarray,
    scores: np.ndarray,
    baseline_scores: np.ndarray,
    repetitions: int,
    seed: int,
) -> list[float] | None:
    if "facility_id" not in frame or frame["facility_id"].nunique() < 2:
        return None
    grouped_indices = {
        str(facility): np.flatnonzero(frame["facility_id"].astype(str).to_numpy() == str(facility))
        for facility in frame["facility_id"].astype(str).unique()
    }
    facilities = list(grouped_indices)
    rng = np.random.default_rng(seed)
    differences: list[float] = []
    attempts = 0
    while len(differences) < repetitions and attempts < repetitions * 10:
        attempts += 1
        selected = rng.choice(facilities, size=len(facilities), replace=True)
        indices = np.concatenate([grouped_indices[value] for value in selected])
        if len(np.unique(y[indices])) < 2:
            continue
        differences.append(
            _safe_pr_auc(y[indices], scores[indices])
            - _safe_pr_auc(y[indices], baseline_scores[indices])
        )
    if len(differences) < repetitions:
        return None
    return [
        float(np.quantile(differences, 0.025)),
        float(np.quantile(differences, 0.975)),
    ]


def _bootstrap_ci(
    frame: pd.DataFrame,
    *,
    y: np.ndarray,
    scores: np.ndarray,
    threshold: float,
    repetitions: int,
    seed: int,
) -> dict[str, Any]:
    if "facility_id" not in frame or frame["facility_id"].nunique() < 2:
        return {
            "pr_auc": None,
            "recall": None,
            "requested_resamples": repetitions,
            "valid_resamples": 0,
            "reason": "At least two distinct facilities are required for clustered bootstrap.",
        }
    groups = {
        str(group): np.flatnonzero(frame["facility_id"].astype(str).to_numpy() == str(group))
        for group in frame["facility_id"].astype(str).unique()
    }
    names = list(groups)
    rng = np.random.default_rng(seed)
    pr_values: list[float] = []
    recall_values: list[float] = []
    attempts = 0
    while len(pr_values) < repetitions and attempts < repetitions * 10:
        attempts += 1
        sample = np.concatenate([groups[name] for name in rng.choice(names, size=len(names), replace=True)])
        if len(np.unique(y[sample])) < 2:
            continue
        pr_values.append(_safe_pr_auc(y[sample], scores[sample]))
        recall_values.append(float(recall_score(y[sample], scores[sample] >= threshold, zero_division=0)))
    complete = len(pr_values) >= repetitions
    return {
        "pr_auc": [
            float(np.quantile(pr_values, 0.025)),
            float(np.quantile(pr_values, 0.975)),
        ] if complete else None,
        "recall": [
            float(np.quantile(recall_values, 0.025)),
            float(np.quantile(recall_values, 0.975)),
        ] if complete else None,
        "requested_resamples": repetitions,
        "valid_resamples": len(pr_values),
        "reason": (
            None if complete else
            "not computed: fewer than the requested number of two-class facility-cluster resamples were available."
        ),
    }


def _subgroups(
    frame: pd.DataFrame,
    *,
    scores: np.ndarray,
    threshold: float,
    minimum_positives: int,
) -> list[dict[str, Any]]:
    results = []
    predicted = scores >= threshold
    for column in ("facility_type", "district", "item_category", "program_funded", "cold_chain"):
        if column not in frame:
            continue
        for value, indices in frame.groupby(column, dropna=False, sort=True).indices.items():
            idx = np.asarray(indices, dtype=int)
            y = pd.to_numeric(frame.iloc[idx]["target"]).astype(int).to_numpy()
            positives = int(y.sum())
            row: dict[str, Any] = {
                "dimension": column,
                "value": "Unknown" if pd.isna(value) else str(value),
                "rows": int(len(idx)),
                "positives": positives,
            }
            if positives < minimum_positives:
                row["status"] = "insufficient data"
            else:
                row.update({
                    "status": "computed",
                    "recall": float(recall_score(y, predicted[idx], zero_division=0)),
                    "precision": float(precision_score(y, predicted[idx], zero_division=0)),
                })
            results.append(row)
    return results


def _lead_time_summary(
    frame: pd.DataFrame,
    *,
    scores: np.ndarray,
    threshold: float,
    frequency: str,
) -> dict[str, Any]:
    if "label_event_offset" not in frame:
        return {
            "status": "not computed",
            "reason": "Feature table does not include observed label-event offsets.",
        }
    target = pd.to_numeric(frame["target"], errors="coerce").to_numpy(dtype=float)
    offsets = pd.to_numeric(frame["label_event_offset"], errors="coerce").to_numpy(dtype=float)
    stockouts = target == 1
    known_event = stockouts & np.isfinite(offsets)
    if not known_event.any():
        return {
            "status": "not computed",
            "reason": "No positive test labels have a known event offset.",
        }
    flagged_early = (scores >= threshold) & known_event & (offsets >= 1)
    lead_unit = "months" if frequency == "monthly" else "days"
    return {
        "status": "computed",
        "unit": lead_unit,
        "stockouts": int(stockouts.sum()),
        "stockouts_with_known_event_offset": int(known_event.sum()),
        "flagged_at_least_one_period_ahead": int(flagged_early.sum()),
        "share_stockouts_flagged_at_least_one_period_ahead": float(
            flagged_early.sum() / stockouts.sum()
        ) if stockouts.sum() else None,
        "lead_time_note": (
            "Monthly lead time is coarse; finer claims require daily data."
            if frequency == "monthly"
            else "Daily event offsets are measured in observed daily periods."
        ),
    }


def _markdown_report(report: dict[str, Any]) -> str:
    header = report["notice"] if report["is_synthetic"] else "Model evaluation report"
    lead_unit = "month" if report["data_frequency"] == "monthly" else "day"
    lines = [
        f"# {header}", "",
        "## What this does and does not show", "",
        report["interpretation"], "",
        "## Test metrics (single held-out pass)", "",
        f"| Model | PR-AUC | ROC-AUC | Brier | Precision | Recall | F1 | Recall at fixed precision | Stock-outs flagged ≥1 {lead_unit} ahead | Rows | Positives |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in report["test_metrics"].items():
        values = [row.get(key) for key in (
            "pr_auc", "roc_auc", "brier", "precision", "recall", "f1",
            "recall_at_fixed_precision",
            "share_stockouts_flagged_at_least_one_period_ahead",
            "rows", "positives",
        )]
        lines.append("| " + name + " | " + " | ".join("not computed" if value is None else str(value) for value in values) + " |")
    lines.extend(["", "## Clustered bootstrap intervals", "", "| Model | PR-AUC 95% CI | Recall 95% CI | PR-AUC difference vs rule 95% CI |", "|---|---|---|---|"])
    for name, row in report["test_metrics"].items():
        intervals = row.get("cluster_bootstrap_95_ci", {})
        difference = row.get("pr_auc_difference_vs_rule_ci")
        lines.append(
            f"| {name} | {intervals.get('pr_auc', 'not computed')} | "
            f"{intervals.get('recall', 'not computed')} | "
            f"{difference if difference is not None else 'not computed'} |"
        )
    lines.extend(["", "## Calibration", "", "```json", json.dumps(report["calibration"], indent=2), "```", ""])
    lines.extend(["## Label prevalence", "", "```json", json.dumps(report["label_prevalence"], indent=2), "```", ""])
    lines.extend(["## Effective sample size", "", "```json", json.dumps(report["effective_sample_size"], indent=2), "```", ""])
    lines.extend(["## Split boundaries", "", "```json", json.dumps(report["split_boundaries"], indent=2), "```", ""])
    lines.extend(["## Feature availability", "", "```json", json.dumps(report["feature_availability"], indent=2), "```", ""])
    lines.extend(["## Source missingness profile", "", "```json", json.dumps(report["source_missingness"], indent=2), "```", ""])
    lines.extend(["## Lead time", "", "```json", json.dumps(report["lead_time"], indent=2), "```", ""])
    lines.extend([
        "## Subgroups", "",
        "| Dimension | Group | Rows | Positives | Status | Precision | Recall |",
        "|---|---|---:|---:|---|---:|---:|",
    ])
    for row in report["subgroups"]:
        lines.append(
            "| " + " | ".join(
                str(row.get(key, "not computed"))
                for key in (
                    "dimension", "value", "rows", "positives", "status",
                    "precision", "recall",
                )
            ) + " |"
        )
    lines.append("")
    lines.extend(["## Unseen-group evaluation", "", "```json", json.dumps(report["unseen_group"], indent=2), "```", ""])
    lines.extend(["## Validation feature importance", "", "```json", json.dumps(report["feature_importance"], indent=2), "```", ""])
    lines.extend(["## Promotion gate", "", "```json", json.dumps(report["gate_results"], indent=2), "```", ""])
    return "\n".join(lines) + "\n"


def train_feature_dataset(
    feature_dataset_id: str,
    *,
    feature_root: Path = FEATURE_ROOT,
    model_root: Path = MODEL_ROOT,
    precision_target: float = 0.5,
    threshold_objective: str = "precision",
    threshold_target: float | None = None,
    minimum_positives: int | None = None,
    minimum_split_positives: int | None = None,
    minimum_group_positives: int = 5,
    minimum_history_periods: int = 24,
    minimum_facilities: int | None = None,
    daily_cover_thresholds: tuple[float, float] = (7.0, 14.0),
    monthly_cover_thresholds: tuple[float, float] = (0.25, 0.5),
    seed: int = DEFAULT_SEED,
    bootstrap_repetitions: int = 1000,
) -> Path:
    if not 0 < precision_target <= 1:
        raise ValueError("precision_target must be in (0, 1].")
    if threshold_objective not in ("precision", "recall"):
        raise ValueError("threshold_objective must be 'precision' or 'recall'.")
    if threshold_objective == "recall" and threshold_target is None:
        raise ValueError("threshold_target is required when threshold_objective is 'recall'.")
    operating_target = (
        precision_target if threshold_target is None else threshold_target
    )
    if not 0 < operating_target <= 1:
        raise ValueError("threshold_target must be in (0, 1].")
    if daily_cover_thresholds[0] >= daily_cover_thresholds[1]:
        raise ValueError("Daily critical threshold must be lower than the moderate threshold.")
    if monthly_cover_thresholds[0] >= monthly_cover_thresholds[1]:
        raise ValueError("Monthly critical threshold must be lower than the moderate threshold.")
    if minimum_split_positives is None:
        minimum_split_positives = minimum_positives
    if minimum_split_positives is not None and minimum_split_positives < 1:
        raise ValueError("minimum_split_positives must be positive.")
    if minimum_group_positives < 1 or minimum_history_periods < 1:
        raise ValueError("Positive minimum counts are required.")
    if bootstrap_repetitions < 1000:
        raise ValueError("At least 1000 facility-cluster bootstrap resamples are required.")
    directory = _resolve_feature_table(feature_dataset_id, feature_root)
    frame, metadata = _load_feature_table(directory)
    frequency = metadata["frequency"]
    if minimum_split_positives is None:
        minimum_split_positives = 30 if frequency == "monthly" else 5
    if minimum_facilities is None:
        minimum_facilities = 12 if frequency == "monthly" else 2
    if minimum_facilities < 2:
        raise ValueError("At least two distinct facilities are required.")
    history_period_count, required_history, distinct_facilities = (
        _validate_training_history(
            frame,
            frequency=frequency,
            minimum_history_periods=minimum_history_periods,
            minimum_facilities=minimum_facilities,
        )
    )
    time_split_valid = _validate_time_split_metadata(frame, metadata)
    _validate_group_split_metadata(frame, metadata)
    is_synthetic = bool(metadata["is_synthetic"])
    provenance_status, verification, verified_dataset_hash = (
        _current_dataset_provenance(metadata)
    )
    _log(f"Starting training for feature build {metadata['build_id']}", is_synthetic=is_synthetic)

    features = _feature_columns(frame, metadata)
    diagnostic = _training_validation_leakage_diagnostics(
        frame,
        features,
        metadata.get("feature_lineage", {}),
    )
    leakage_warnings = (
        diagnostic.get("future_stock_feature_warnings", [])
        + diagnostic.get("probable_leak_or_trivial_rule", [])
        + diagnostic.get("high_correlations", [])
    )
    split_frames: dict[str, pd.DataFrame] = {}
    for split_name in ("train", "validation"):
        part = frame.loc[frame["time_split"] == split_name]
        part = part.loc[part["target"].notna()].copy()
        _validate_labeled_split_summary(
            split_name,
            part,
            metadata["split_boundaries"]["time_based"][split_name],
        )
        if is_synthetic and not part["is_synthetic"].map(
            lambda value: str(value).strip().casefold() == "true"
        ).all():
            raise ValueError(f"Synthetic {split_name} rows are missing is_synthetic=true.")
        _validate_split_positives(
            split_name, part, minimum_positives=minimum_split_positives
        )
        split_frames[split_name] = part
    train = split_frames["train"]
    validation = split_frames["validation"]
    x_train, y_train = _split_xy(train, features)
    x_validation, y_validation = _split_xy(validation, features)

    parameters, fitted_models, validation_pr = _best_validation_parameters(
        x_train, y_train, x_validation, y_validation, seed=seed
    )
    validation_scores: dict[str, np.ndarray] = {
        name: _probabilities(model, x_validation)
        for name, model in fitted_models.items()
    }
    thresholds: dict[str, float] = {}
    threshold_selection: dict[str, dict[str, Any]] = {}
    validation_calibration: dict[str, dict[str, Any]] = {}
    calibrated_validation_scores: dict[str, np.ndarray] = {}
    for name, scores in validation_scores.items():
        (
            calibrated_validation,
            calibrator,
            threshold,
            selection,
            calibration,
        ) = _validation_policy(
            y_validation,
            scores,
            operating_target,
            threshold_objective=threshold_objective,
        )
        validation_calibration[name] = {
            **calibration,
            "calibrator": calibrator,
        }
        calibrated_validation_scores[name] = calibrated_validation
        thresholds[name] = threshold
        threshold_selection[name] = selection

    chosen_model_name = max(
        validation_pr,
        key=lambda name: float("-inf")
        if validation_pr[name] is None
        else float(validation_pr[name]),
    )
    cover_thresholds = (
        daily_cover_thresholds
        if metadata["frequency"] == "daily"
        else monthly_cover_thresholds
    )
    rule_validation_scores = _rule_scores(
        validation,
        metadata["frequency"],
        critical_limit=cover_thresholds[0],
        moderate_limit=cover_thresholds[1],
    )
    rule_threshold, rule_threshold_selection = _select_operating_threshold(
        y_validation,
        rule_validation_scores,
        operating_target,
        threshold_objective,
    )
    validation_builder_end = metadata.get("split_boundaries", {}).get("time_based", {}).get("train_period_end")
    if not validation_builder_end:
        raise ValueError("Feature dataset metadata is missing train split boundaries.")

    # This is the sole point where test rows are read. All selection is complete above.
    _log(
        "Accessing the temporal test split once for final evaluation.",
        is_synthetic=is_synthetic,
    )
    test_guard = TestSetAccessGuard(
        lambda: frame.loc[frame["time_split"] == "test"]
        .loc[lambda rows: rows["target"].notna()]
        .copy()
    )
    test = test_guard.evaluate_once()
    _validate_labeled_split_summary(
        "test",
        test,
        metadata["split_boundaries"]["time_based"]["test"],
    )
    y_test = pd.to_numeric(test["target"], errors="raise").astype(int).to_numpy()
    _validate_split_positives(
        "test",
        test,
        minimum_positives=minimum_split_positives,
        require_both_classes=False,
    )
    if is_synthetic and not test["is_synthetic"].map(
        lambda value: str(value).strip().casefold() == "true"
    ).all():
        raise ValueError("Synthetic test rows are missing is_synthetic=true.")
    x_test, _ = _split_xy(test, features)

    prediction_scores: dict[str, np.ndarray] = {}
    calibration_report: dict[str, Any] = {}
    for name, model in fitted_models.items():
        raw_test_scores = _probabilities(model, x_test)
        calibrator = validation_calibration[name]["calibrator"]
        calibrated_test_scores = _apply_calibrator(calibrator, raw_test_scores)
        prediction_scores[name] = calibrated_test_scores
        val_calibrated = calibrated_validation_scores[name]
        calibration_report[name] = {
            "method": validation_calibration[name]["method"],
            "fit_data": validation_calibration[name].get("fit_data"),
            "reason": validation_calibration[name].get("reason"),
            "validation_brier_before": validation_calibration[name]["brier_before"],
            "validation_brier_after": validation_calibration[name]["brier_after"],
            "test_brier_before": float(brier_score_loss(y_test, np.clip(raw_test_scores, 0, 1))),
            "test_brier_after": float(brier_score_loss(y_test, np.clip(calibrated_test_scores, 0, 1))),
            "validation_calibration_curve": _calibration_curve(y_validation, val_calibrated),
        }

    rule_scores = _rule_scores(
        test,
        metadata["frequency"],
        critical_limit=cover_thresholds[0],
        moderate_limit=cover_thresholds[1],
    )
    rule_operating_threshold = rule_threshold
    persistence = (
        pd.to_numeric(test["stockout_previous_period"], errors="coerce")
        .fillna(-0.5)
        .to_numpy(dtype=float)
        if "stockout_previous_period" in test
        else np.zeros(len(test), dtype=float)
    )
    rule_metrics = _metric_summary(y_test, rule_scores, rule_operating_threshold)
    rule_metrics["confidence_threshold_selection"] = rule_threshold_selection
    rule_metrics["precision_target_attained_on_validation"] = bool(
        rule_threshold_selection["precision_target_attained"]
    )
    rule_metrics["recall_at_fixed_precision"] = (
        rule_metrics["recall"]
        if (
            threshold_objective == "precision"
            and rule_threshold_selection["precision_target_attained"]
        )
        else None
    )
    rule_metrics["fixed_precision_target"] = (
        precision_target
        if (
            threshold_objective == "precision"
            and rule_threshold_selection["precision_target_attained"]
        )
        else None
    )
    rule_metrics["cluster_bootstrap_95_ci"] = _bootstrap_ci(
        test, y=y_test, scores=rule_scores, threshold=rule_operating_threshold,
        repetitions=bootstrap_repetitions, seed=seed,
    )
    persistence_metrics = _metric_summary(y_test, persistence, 0.5)
    persistence_metrics["cluster_bootstrap_95_ci"] = _bootstrap_ci(
        test, y=y_test, scores=persistence, threshold=0.5,
        repetitions=bootstrap_repetitions, seed=seed + 2,
    )
    test_metric_results: dict[str, dict[str, Any]] = {
        "rule_baseline": rule_metrics,
        "persistence_baseline": persistence_metrics,
    }
    seasonal_column = "stockout_same_period_last_year"
    if seasonal_column in test:
        seasonal_scores = pd.to_numeric(test[seasonal_column], errors="coerce").fillna(-0.5).to_numpy(dtype=float)
        test_metric_results["seasonal_naive"] = _metric_summary(y_test, seasonal_scores, 0.5)
        test_metric_results["seasonal_naive"]["cluster_bootstrap_95_ci"] = _bootstrap_ci(
            test, y=y_test, scores=seasonal_scores, threshold=0.5,
            repetitions=bootstrap_repetitions, seed=seed + 3,
        )
    else:
        test_metric_results["seasonal_naive"] = {
            "status": "not computed",
            "reason": (
                "not computed: insufficient history for a monthly same-period-last-year baseline."
                if metadata["frequency"] == "monthly"
                else "not computed: insufficient daily history for a same-period-last-year baseline."
            ),
        }

    for name, scores in prediction_scores.items():
        threshold = thresholds[name]
        metrics = _metric_summary(y_test, scores, threshold)
        metrics["confidence_threshold_selection"] = threshold_selection[name]
        metrics["precision_target_attained_on_validation"] = bool(
            threshold_selection[name]["precision_target_attained"]
        )
        metrics["validation_pr_auc"] = validation_pr[name]
        metrics["selected_parameters"] = parameters[name]
        metrics["cluster_bootstrap_95_ci"] = _bootstrap_ci(
            test, y=y_test, scores=scores, threshold=threshold,
            repetitions=bootstrap_repetitions, seed=seed,
        )
        difference_interval = _cluster_bootstrap_pr_difference(
            test, y=y_test, scores=scores, baseline_scores=rule_scores,
            repetitions=bootstrap_repetitions, seed=seed + 1,
        )
        metrics["pr_auc_difference_vs_rule_ci"] = difference_interval
        metrics["pr_auc_difference_vs_rule_bootstrap_resamples"] = (
            bootstrap_repetitions if difference_interval is not None else 0
        )
        if metrics["cluster_bootstrap_95_ci"]["reason"] is not None:
            metrics["not_computed_reasons"]["cluster_bootstrap_95_ci"] = (
                metrics["cluster_bootstrap_95_ci"]["reason"]
            )
        if difference_interval is None:
            metrics["not_computed_reasons"]["pr_auc_difference_vs_rule_ci"] = (
                "not computed: insufficient valid two-class facility-cluster resamples."
            )
        metrics["recall_at_fixed_precision"] = (
            metrics["recall"]
            if (
                threshold_objective == "precision"
                and threshold_selection[name]["precision_target_attained"]
            )
            else None
        )
        metrics["fixed_precision_target"] = (
            precision_target
            if (
                threshold_objective == "precision"
                and threshold_selection[name]["precision_target_attained"]
            )
            else None
        )
        metrics["stockouts_caught_share"] = metrics["recall"]
        test_metric_results[name] = metrics

    selected_metrics = test_metric_results[chosen_model_name]
    for model_name, metrics in test_metric_results.items():
        if metrics.get("status") == "not computed":
            continue
        metric_scores = (
            rule_scores if model_name == "rule_baseline"
            else persistence if model_name == "persistence_baseline"
            else seasonal_scores if model_name == "seasonal_naive" and seasonal_column in test
            else prediction_scores.get(model_name)
        )
        metric_threshold = (
            rule_operating_threshold if model_name == "rule_baseline"
            else thresholds.get(model_name, 0.5)
        )
        if metric_scores is not None:
            metrics["share_stockouts_flagged_at_least_one_period_ahead"] = (
                _lead_time_summary(
                    test,
                    scores=metric_scores,
                    threshold=metric_threshold,
                    frequency=metadata["frequency"],
                ).get("share_stockouts_flagged_at_least_one_period_ahead")
            )
    group_train = frame.loc[
        (frame["group_split"] == "train")
        & (frame["time_split"] == "train")
    ]
    group_train = group_train.loc[group_train["target"].notna()].copy()
    group_validation = frame.loc[
        (frame["group_split"] == "train")
        & (frame["time_split"] == "validation")
    ]
    group_validation = group_validation.loc[group_validation["target"].notna()].copy()
    group_test_guard = TestSetAccessGuard(
        lambda: frame.loc[frame["group_split"] == "test"]
        .loc[lambda rows: rows["target"].notna()]
        .copy()
    )
    unseen_recall: float | None = None
    group_result: dict[str, Any] = {
        "status": "not computed",
        "test_rows": None,
    }
    if (
        not group_train.empty
        and not group_validation.empty
        and int(pd.to_numeric(group_train["target"]).sum()) >= minimum_split_positives
        and int(pd.to_numeric(group_validation["target"]).sum()) >= minimum_split_positives
    ):
        group_x_train, group_y_train = _split_xy(group_train, features)
        group_x_validation, group_y_validation = _split_xy(group_validation, features)
        group_model = _fit_group_model(
            chosen_model_name, parameters[chosen_model_name],
            group_x_train, group_y_train, seed=seed,
        )
        group_val_scores = _probabilities(group_model, group_x_validation)
        (
            group_val_scores,
            group_calibrator,
            group_threshold,
            group_threshold_detail,
            _,
        ) = _validation_policy(
            group_y_validation,
            group_val_scores,
            operating_target,
            threshold_objective=threshold_objective,
        )
        unseen_test = group_test_guard.evaluate_once()
        group_test_summary = metadata["split_boundaries"]["unseen_group"]["test"]
        _validate_labeled_split_summary(
            "unseen-group test",
            unseen_test,
            group_test_summary,
        )
        group_result["test_rows"] = len(unseen_test)
        group_test_positives = int(pd.to_numeric(unseen_test["target"]).sum())
        if group_test_positives >= minimum_split_positives:
            group_x_test, group_y_test = _split_xy(unseen_test, features)
            group_test_scores = _probabilities(group_model, group_x_test)
            group_test_scores = _apply_calibrator(group_calibrator, group_test_scores)
            group_metrics = _metric_summary(group_y_test, group_test_scores, group_threshold)
            unseen_recall = group_metrics["recall"]
            group_result = {
                "status": "computed",
                "test_rows": len(unseen_test),
                "model": chosen_model_name,
                "metrics": group_metrics,
                "threshold_selection": group_threshold_detail,
                "groups": sorted(unseen_test["facility_id"].astype(str).unique().tolist()),
                "test_access_count": group_test_guard.access_count,
            }
        else:
            group_result.update(
                {
                    "reason": (
                        f"Unseen-group test split has {group_test_positives} positives; "
                        f"at least {minimum_split_positives} are required."
                    ),
                    "test_access_count": group_test_guard.access_count,
                }
            )
    else:
        group_result["reason"] = (
            "Grouped train, validation, and test partitions each require at least "
            f"{minimum_split_positives} positives."
        )

    gate = evaluate_promotion_gate(
        is_synthetic=is_synthetic,
        time_based_split=time_split_valid,
        provenance_status=provenance_status,
        dataset_hash=metadata.get("dataset_hash"),
        verified_dataset_hash=verified_dataset_hash,
        test_metrics={
            "rule_baseline": test_metric_results["rule_baseline"],
            "selected_model": selected_metrics,
        },
        gate_diagnostics={
            "unseen_recall": unseen_recall,
            "leakage_warnings": leakage_warnings,
            "history_period_count": history_period_count,
            "minimum_history_periods": required_history,
            "positive_counts_per_split": {
                name: int(pd.to_numeric(part["target"]).sum())
                for name, part in split_frames.items()
            } | {"test": int(y_test.sum())},
            "minimum_positives_per_split": minimum_split_positives,
            "distinct_facilities": distinct_facilities,
            "minimum_facilities": minimum_facilities,
        },
    )

    lead_time = {
        "frequency": metadata["frequency"],
        "unit": "months" if metadata["frequency"] == "monthly" else "days",
        "rule_baseline": _lead_time_summary(
            test,
            scores=rule_scores,
            threshold=rule_operating_threshold,
            frequency=metadata["frequency"],
        ),
        "selected_model": _lead_time_summary(
            test,
            scores=prediction_scores[chosen_model_name],
            threshold=thresholds[chosen_model_name],
            frequency=metadata["frequency"],
        ),
        "note": (
            "Monthly lead time is coarse by design; finer lead-time claims require daily data."
            if metadata["frequency"] == "monthly"
            else "Daily event offsets are measured in observed daily periods."
        ),
    }
    effective_sample_size = {
        "all_labeled": {
            "rows": int(frame["target"].notna().sum()),
            "positives": int(pd.to_numeric(frame["target"], errors="coerce").fillna(0).sum()),
            "distinct_facilities": int(frame.loc[frame["target"].notna(), "facility_id"].nunique()),
        }
    }
    dataset_dates = pd.to_datetime(frame["date"])
    dataset_date_range = {
        "start": dataset_dates.min().date().isoformat(),
        "end": dataset_dates.max().date().isoformat(),
    }
    for split_name, part in {
        "train": train,
        "validation": validation,
        "test": test,
    }.items():
        effective_sample_size[split_name] = {
            "labeled_rows": len(part),
            "positives": int(pd.to_numeric(part["target"]).sum()),
            "distinct_facilities": int(part["facility_id"].nunique()),
        }
    model_version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    artifact_dir = _create_artifact_directory(model_root, model_version)
    training_dates = pd.to_datetime(train["date"])
    metadata_out = {
        "notice": "SYNTHETIC - not evidence of real-world performance" if is_synthetic else "Model evaluation artifact",
        "model_version": model_version,
        "time_based_split": time_split_valid,
        "test_metrics": selected_metrics,
        "all_test_metrics": test_metric_results,
        "training_date_range": {
            "start": training_dates.min().date().isoformat(),
            "end": training_dates.max().date().isoformat(),
        },
        "data_hash": metadata["dataset_hash"],
        "provenance_status": provenance_status,
        "verification": verification,
        "verified_dataset_hash": verified_dataset_hash,
        "feature_table_sha256": metadata["feature_table_sha256"],
        "feature_table_row_count": metadata["feature_table_row_count"],
        "row_count": metadata["row_count"],
        "feature_dataset_id": metadata["build_id"],
        "source_dataset_id": metadata.get("dataset_id"),
        "feature_list": features,
        "label_mode": metadata["label_mode"],
        "split_boundaries": metadata["split_boundaries"],
        "dataset_date_range": dataset_date_range,
        "horizon_periods": int(metadata["horizon"]),
        "horizon_days": int(metadata["horizon"]) if metadata["frequency"] == "daily" else None,
        "data_frequency": metadata["frequency"],
        "is_synthetic": is_synthetic,
        "threshold": thresholds[chosen_model_name],
        "rule_cover_thresholds": {
            "critical_below": cover_thresholds[0],
            "moderate_through": cover_thresholds[1],
            "unit": "days" if metadata["frequency"] == "daily" else "months",
        },
        "threshold_selection": threshold_selection[chosen_model_name],
        "gate_results": gate,
        "promotion_diagnostics": {
            "unseen_recall": unseen_recall,
            "leakage_warnings": leakage_warnings,
            "history_period_count": history_period_count,
            "minimum_history_periods": required_history,
            "positive_counts_per_split": {
                name: int(pd.to_numeric(part["target"]).sum())
                for name, part in split_frames.items()
            } | {"test": int(y_test.sum())},
            "minimum_positives_per_split": minimum_split_positives,
            "distinct_facilities": distinct_facilities,
            "minimum_facilities": minimum_facilities,
        },
        "selected_model": chosen_model_name,
        "model_validated": bool(
            gate["model_validated"]
            and not is_synthetic
            and provenance_status == "verified"
            and verified_dataset_hash == metadata["dataset_hash"]
        ),
        "library_versions": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "random_seed": seed,
        "git_commit": _git_commit(),
        "calibration": calibration_report[chosen_model_name],
        "feature_builder_state": metadata["feature_builder_state"],
        "source_missingness": metadata.get("source_missingness"),
        "evaluation_integrity": {
            "feature_table_hash_verified": True,
            "feature_table_row_count_verified": True,
            "build_id_verified": True,
            "row_provenance_verified": True,
            "time_based_split_verified": time_split_valid,
            "grouped_split_verified": True,
            "test_label_diagnostics_used_before_final_pass": False,
        },
        "validation_only_tuning": parameters,
        "validation_thresholds": {
            "models": thresholds,
            "rule_baseline": rule_operating_threshold,
            "target": operating_target,
            "precision_target": operating_target if threshold_objective == "precision" else None,
            "recall_target": operating_target if threshold_objective == "recall" else None,
            "threshold_objective": threshold_objective,
        },
        "effective_sample_size": effective_sample_size,
        "history_period_count": history_period_count,
        "minimum_history_periods": required_history,
        "minimum_split_positives": minimum_split_positives,
        "distinct_facilities": distinct_facilities,
        "minimum_facilities": minimum_facilities,
        "test_access_count": test_guard.access_count,
        "unseen_group": {
            "group_column": metadata.get("group_column"),
            "test_rows": group_result.get("test_rows"),
            "recall": unseen_recall,
            "status": "computed" if unseen_recall is not None else "not computed",
            "results": group_result,
            "recall_difference_vs_time_split": (
                unseen_recall - selected_metrics["recall"]
                if unseen_recall is not None else None
            ),
        },
    }
    artifact_payload = {
        "estimators": fitted_models,
        "calibrators": {
            name: detail["calibrator"] for name, detail in validation_calibration.items()
        },
        "selected_model": chosen_model_name,
        "thresholds": thresholds,
        "feature_builder_state": metadata_out["feature_builder_state"],
    }
    joblib.dump(artifact_payload, artifact_dir / "model.joblib")
    joblib.dump(
        artifact_payload["calibrators"],
        artifact_dir / "calibrators.joblib",
    )
    (artifact_dir / "feature_builder_state.json").write_text(
        json.dumps(
            metadata_out["feature_builder_state"],
            indent=2,
            allow_nan=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    metadata_out["artifact_sha256"] = {
        name: _sha256_file(artifact_dir / name)
        for name in (
            "model.joblib",
            "calibrators.joblib",
            "feature_builder_state.json",
        )
    }
    metadata_path = artifact_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata_out, indent=2, allow_nan=False, default=_json_default), encoding="utf-8")
    report = {
        "notice": metadata_out["notice"],
        "is_synthetic": is_synthetic,
        "interpretation": (
            "This run uses synthetic data designed to test signal recovery. It is not evidence of real-world performance. Results apply only to the facilities, items, and time range in this generated dataset."
            if is_synthetic else
            "This is a single held-out evaluation under the recorded data and split design. Results apply only to the facilities, items, and time range in this dataset; they do not establish causal impact or deployment readiness."
        ),
        "dataset_date_range": dataset_date_range,
        "facility_count": distinct_facilities,
        "item_count": int(frame["item_id"].nunique()),
        "test_metrics": test_metric_results,
        "calibration": calibration_report,
        "label_prevalence": metadata.get("label_prevalence"),
        "effective_sample_size": effective_sample_size,
        "split_boundaries": metadata.get("split_boundaries"),
        "data_frequency": metadata["frequency"],
        "horizon_periods": int(metadata["horizon"]),
        "feature_availability": metadata.get("feature_availability", {}),
        "source_missingness": metadata.get("source_missingness"),
        "lead_time": lead_time,
        "subgroups": _subgroups(
            test, scores=prediction_scores[chosen_model_name],
            threshold=thresholds[chosen_model_name],
            minimum_positives=minimum_group_positives,
        ),
        "gate_results": gate,
        "selected_model": chosen_model_name,
        "unseen_group": metadata_out["unseen_group"],
        "feature_importance": _validation_importance(
            fitted_models[chosen_model_name],
            fitted_models["hist_gradient_boosting"],
            x_validation,
            y_validation,
            features,
            seed,
        ),
    }
    (artifact_dir / "evaluation_report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False, default=_json_default), encoding="utf-8"
    )
    (artifact_dir / "evaluation_report.md").write_text(_markdown_report(report), encoding="utf-8")
    _log(f"Training evaluation completed: {artifact_dir}", is_synthetic=is_synthetic)
    return artifact_dir


def _validation_importance(
    estimator: Any,
    tree_estimator: Any,
    x_validation: pd.DataFrame,
    y_validation: np.ndarray,
    feature_names: list[str],
    seed: int,
) -> dict[str, Any]:
    try:
        result = permutation_importance(
            estimator,
            x_validation,
            y_validation,
            scoring="average_precision",
            n_repeats=2,
            random_state=seed,
        )
    except (ValueError, TypeError) as exc:
        return {"permutation": [], "status": "not computed", "reason": str(exc), "shap": "not computed"}
    permutation = sorted(
        (
            {
                "feature": feature_names[index],
                "mean_importance": float(result.importances_mean[index]),
                "std_importance": float(result.importances_std[index]),
            }
            for index in range(len(feature_names))
        ),
        key=lambda item: item["mean_importance"],
        reverse=True,
    )
    shap_result: dict[str, Any]
    if importlib.util.find_spec("shap") is None:
        shap_result = {"status": "not computed: SHAP is not installed"}
    else:
        try:
            import shap

            preprocessor = tree_estimator.named_steps["preprocess"]
            classifier = tree_estimator.named_steps["classifier"]
            transformed = preprocessor.transform(x_validation.iloc[: min(100, len(x_validation))])
            values = shap.TreeExplainer(classifier).shap_values(transformed)
            if isinstance(values, list):
                values = values[-1]
            values = np.asarray(values)
            if values.ndim == 3:
                values = values[:, :, -1]
            names = preprocessor.get_feature_names_out()
            shap_result = {
                "status": "computed on validation rows only",
                "mean_absolute_values": [
                    {"feature": str(name), "mean_abs_shap": float(value)}
                    for name, value in zip(names, np.mean(np.abs(values), axis=0))
                ],
            }
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            shap_result = {
                "status": "not computed",
                "reason": f"SHAP does not support this tree configuration: {exc}",
            }
    return {
        "permutation": permutation,
        "scoring": "validation average precision",
        "shap": shap_result,
    }


def _calibration_curve(y: np.ndarray, scores: np.ndarray) -> list[dict[str, Any]]:
    rows = []
    for lower, upper in zip(np.linspace(0, 1, 11)[:-1], np.linspace(0, 1, 11)[1:]):
        mask = (scores >= lower) & (scores <= upper if upper == 1 else scores < upper)
        if mask.any():
            rows.append({
                "mean_predicted": float(scores[mask].mean()),
                "observed_fraction": float(y[mask].mean()),
                "count": int(mask.sum()),
            })
    return rows


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train and evaluate models on a Phase 3 feature dataset."
    )
    parser.add_argument("feature_dataset_id", help="Unique build ID emitted by ml.build_dataset")
    parser.add_argument("--feature-root", type=Path, default=FEATURE_ROOT)
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--precision-target", type=float, default=0.5)
    parser.add_argument("--threshold-objective", choices=("precision", "recall"), default="precision")
    parser.add_argument("--threshold-target", "--recall-target", type=float)
    parser.add_argument("--minimum-positives", "--minimum-split-positives", dest="minimum_split_positives", type=int)
    parser.add_argument("--minimum-group-positives", type=int, default=5)
    parser.add_argument("--minimum-history-periods", type=int, default=24)
    parser.add_argument("--minimum-facilities", type=int)
    parser.add_argument("--daily-critical-days", type=float, default=7.0)
    parser.add_argument("--daily-moderate-days", type=float, default=14.0)
    parser.add_argument("--monthly-critical-cover", type=float, default=0.25)
    parser.add_argument("--monthly-moderate-cover", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    args = parser.parse_args()
    artifact = train_feature_dataset(
        args.feature_dataset_id,
        feature_root=args.feature_root,
        model_root=args.model_root,
        precision_target=args.precision_target,
        threshold_objective=args.threshold_objective,
        threshold_target=args.threshold_target,
        minimum_split_positives=args.minimum_split_positives,
        minimum_group_positives=args.minimum_group_positives,
        minimum_history_periods=args.minimum_history_periods,
        minimum_facilities=args.minimum_facilities,
        daily_cover_thresholds=(
            args.daily_critical_days,
            args.daily_moderate_days,
        ),
        monthly_cover_thresholds=(
            args.monthly_critical_cover,
            args.monthly_moderate_cover,
        ),
        seed=args.seed,
        bootstrap_repetitions=args.bootstrap_repetitions,
    )
    artifact_metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
    prefix = _log_prefix(bool(artifact_metadata["is_synthetic"]))
    print(f"{prefix}Artifact saved: {artifact}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
