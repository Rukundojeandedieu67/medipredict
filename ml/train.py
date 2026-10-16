from __future__ import annotations

import argparse
from datetime import datetime, timezone
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

from .promote import evaluate_promotion_gate

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
        "dataset_id", "dataset_hash", "build_id", "frequency", "horizon",
        "feature_list", "feature_builder_state", "is_synthetic", "validation", "split_boundaries",
        "leakage_diagnostics",
    )
    missing = [field for field in required if field not in metadata]
    if missing:
        raise ValueError(f"Feature dataset metadata is missing: {', '.join(missing)}")
    if metadata.get("validation", {}).get("valid") is not True:
        raise ValueError("Feature dataset failed validation.")
    if metadata["frequency"] not in ("daily", "monthly") or int(metadata["horizon"]) < 1:
        raise ValueError("Feature dataset has invalid frequency or horizon metadata.")
    if metadata["feature_builder_state"].get("feature_list") != metadata["feature_list"]:
        raise ValueError("FeatureBuilder state does not match the feature dataset schema.")
    if not isinstance(metadata["is_synthetic"], bool):
        raise ValueError("Feature dataset is missing a valid is_synthetic metadata flag.")
    frame = pd.read_csv(features_path)
    required_columns = {
        "target", "time_split", "group_split", "facility_id", "date", "is_synthetic"
    }
    absent = sorted(required_columns.difference(frame.columns))
    if absent:
        raise ValueError(f"Feature table is missing required columns: {', '.join(absent)}")
    return frame, metadata


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
    if not columns:
        raise ValueError("No declared Phase 3 features are present in the feature table.")
    return columns


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
    logistic_best = max(logistic_candidates, key=lambda item: item[0])
    tree_best = max(tree_candidates, key=lambda item: item[0])
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


def _safe_pr_auc(y: np.ndarray, scores: np.ndarray) -> float:
    return float(average_precision_score(y, scores)) if len(np.unique(y)) > 1 else float("nan")


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
            "validation_precision": selected[2],
            "validation_recall": selected[0],
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
            "validation_precision": float(precision[index]),
            "validation_recall": float(recall[index]),
        }
    return 0.5, {
        "selection": "fixed default; validation scores had no thresholds",
        "precision_target": precision_target,
    }


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
    for _ in range(repetitions):
        selected = rng.choice(facilities, size=len(facilities), replace=True)
        indices = np.concatenate([grouped_indices[value] for value in selected])
        if len(np.unique(y[indices])) < 2:
            continue
        differences.append(
            _safe_pr_auc(y[indices], scores[indices])
            - _safe_pr_auc(y[indices], baseline_scores[indices])
        )
    if not differences:
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
) -> dict[str, list[float] | None]:
    if "facility_id" not in frame or frame["facility_id"].nunique() < 2:
        return {"pr_auc": None, "recall": None}
    groups = {
        str(group): np.flatnonzero(frame["facility_id"].astype(str).to_numpy() == str(group))
        for group in frame["facility_id"].astype(str).unique()
    }
    names = list(groups)
    rng = np.random.default_rng(seed)
    pr_values: list[float] = []
    recall_values: list[float] = []
    for _ in range(repetitions):
        sample = np.concatenate([groups[name] for name in rng.choice(names, size=len(names), replace=True)])
        if len(np.unique(y[sample])) < 2:
            continue
        pr_values.append(_safe_pr_auc(y[sample], scores[sample]))
        recall_values.append(float(recall_score(y[sample], scores[sample] >= threshold, zero_division=0)))
    return {
        "pr_auc": [float(np.quantile(pr_values, 0.025)), float(np.quantile(pr_values, 0.975))] if pr_values else None,
        "recall": [float(np.quantile(recall_values, 0.025)), float(np.quantile(recall_values, 0.975))] if recall_values else None,
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


def _markdown_report(report: dict[str, Any]) -> str:
    header = report["notice"] if report["is_synthetic"] else "Model evaluation report"
    lines = [
        f"# {header}", "",
        "## What this does and does not show", "",
        report["interpretation"], "",
        "## Test metrics (single held-out pass)", "",
        "| Model | PR-AUC | ROC-AUC | Brier | Precision | Recall | F1 | Rows | Positives |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in report["test_metrics"].items():
        values = [row.get(key) for key in ("pr_auc", "roc_auc", "brier", "precision", "recall", "f1", "rows", "positives")]
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
    lines.extend(["## Feature availability", "", "```json", json.dumps(report["feature_availability"], indent=2), "```", ""])
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
    minimum_positives: int = 1,
    minimum_split_positives: int = 5,
    minimum_group_positives: int = 5,
    seed: int = DEFAULT_SEED,
    bootstrap_repetitions: int = 200,
) -> Path:
    if not 0 < precision_target <= 1:
        raise ValueError("precision_target must be in (0, 1].")
    if minimum_positives < 1 or minimum_split_positives < 1 or minimum_group_positives < 1:
        raise ValueError("Positive minimum counts are required.")
    directory = _resolve_feature_table(feature_dataset_id, feature_root)
    frame, metadata = _load_feature_table(directory)
    is_synthetic = bool(metadata["is_synthetic"])
    _log(f"Starting training for feature build {metadata['build_id']}", is_synthetic=is_synthetic)

    diagnostic = metadata["leakage_diagnostics"]
    leakage_warnings = (
        diagnostic.get("future_stock_feature_warnings", [])
        + diagnostic.get("probable_leak_or_trivial_rule", [])
        + diagnostic.get("high_correlations", [])
    )
    features = _feature_columns(frame, metadata)
    split_frames: dict[str, pd.DataFrame] = {}
    for split_name in ("train", "validation"):
        part = frame.loc[(frame["time_split"] == split_name) & frame["target"].notna()].copy()
        if is_synthetic and not part["is_synthetic"].map(
            lambda value: str(value).strip().casefold() == "true"
        ).all():
            raise ValueError(f"Synthetic {split_name} rows are missing is_synthetic=true.")
        positives = int(pd.to_numeric(part["target"]).sum())
        if positives < minimum_split_positives:
            raise ValueError(
                f"{split_name} split has {positives} positives; at least "
                f"{minimum_split_positives} are required."
            )
        split_frames[split_name] = part
    split_summary = metadata["split_boundaries"].get("time_based", {})
    test_summary = split_summary.get("test", {})
    if int(test_summary.get("positive_count", -1)) < minimum_split_positives:
        raise ValueError(
            "test split metadata does not report the configured minimum positive labels."
        )
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
        calibrator = IsotonicRegression(out_of_bounds="clip")
        if len(np.unique(y_validation)) > 1 and len(y_validation) >= 20:
            calibrator.fit(scores, y_validation)
            calibrated_validation = calibrator.predict(scores)
            validation_calibration[name] = {
                "method": "isotonic",
                "fit_data": "validation predictions and labels only",
                "brier_before": float(brier_score_loss(y_validation, scores)),
                "brier_after": float(brier_score_loss(y_validation, calibrated_validation)),
                "calibrator": calibrator,
            }
        else:
            calibrated_validation = scores
            validation_calibration[name] = {
                "method": None,
                "reason": "validation requires at least 20 rows and both classes",
                "brier_before": float(brier_score_loss(y_validation, scores)),
                "brier_after": None,
                "calibrator": None,
            }
        calibrated_validation_scores[name] = calibrated_validation
        thresholds[name], threshold_selection[name] = _threshold_for_precision(
            y_validation, calibrated_validation, precision_target
        )

    chosen_model_name = max(validation_pr, key=validation_pr.get)
    validation_builder_end = metadata.get("split_boundaries", {}).get("time_based", {}).get("train_period_end")
    if not validation_builder_end:
        raise ValueError("Feature dataset metadata is missing train split boundaries.")

    # This is the sole point where test rows are read. All selection is complete above.
    test_guard = TestSetAccessGuard(
        lambda: frame.loc[
            (frame["time_split"] == "test") & frame["target"].notna()
        ].copy()
    )
    test = test_guard.evaluate_once()
    if is_synthetic and not test["is_synthetic"].map(
        lambda value: str(value).strip().casefold() == "true"
    ).all():
        raise ValueError("Synthetic test rows are missing is_synthetic=true.")
    x_test, y_test = _split_xy(test, features)

    prediction_scores: dict[str, np.ndarray] = {}
    calibration_report: dict[str, Any] = {}
    for name, model in fitted_models.items():
        raw_test_scores = _probabilities(model, x_test)
        calibrator = validation_calibration[name]["calibrator"]
        if calibrator is not None:
            calibrated_test_scores = calibrator.predict(raw_test_scores)
        else:
            calibrated_test_scores = raw_test_scores
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

    cover_column = "days_of_cover" if metadata["frequency"] == "daily" else "months_of_stock"
    if cover_column in test:
        cover = pd.to_numeric(test[cover_column], errors="coerce").to_numpy(dtype=float)
        daily_thresholds = (7, 14)
        thresholds_native = daily_thresholds if metadata["frequency"] == "daily" else (1, 2)
        rule_predictions = np.where(cover < thresholds_native[0], 2, np.where(cover <= thresholds_native[1], 1, 0))
        rule_scores = rule_predictions.astype(float) / 2.0
        rule_operating_threshold = 0.5
    else:
        rule_scores = np.zeros(len(test), dtype=float)
        rule_operating_threshold = 1.0
    persistence = (
        pd.to_numeric(test["historical_stockout_count"], errors="coerce").fillna(0).gt(0).to_numpy(dtype=float)
        if "historical_stockout_count" in test else np.zeros(len(test), dtype=float)
    )
    rule_metrics = _metric_summary(y_test, rule_scores, rule_operating_threshold)
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
        seasonal_scores = pd.to_numeric(test[seasonal_column], errors="coerce").fillna(0).to_numpy(dtype=float)
        test_metric_results["seasonal_naive"] = _metric_summary(y_test, seasonal_scores, 0.5)
        test_metric_results["seasonal_naive"]["cluster_bootstrap_95_ci"] = _bootstrap_ci(
            test, y=y_test, scores=seasonal_scores, threshold=0.5,
            repetitions=bootstrap_repetitions, seed=seed + 3,
        )
    else:
        test_metric_results["seasonal_naive"] = {
            "status": "not computed",
            "reason": "Feature table has no same-period-last-year stock-out observation.",
        }

    for name, scores in prediction_scores.items():
        threshold = thresholds[name]
        metrics = _metric_summary(y_test, scores, threshold)
        metrics["confidence_threshold_selection"] = threshold_selection[name]
        metrics["validation_pr_auc"] = validation_pr[name]
        metrics["selected_parameters"] = parameters[name]
        metrics["cluster_bootstrap_95_ci"] = _bootstrap_ci(
            test, y=y_test, scores=scores, threshold=threshold,
            repetitions=bootstrap_repetitions, seed=seed,
        )
        metrics["pr_auc_difference_vs_rule_ci"] = _cluster_bootstrap_pr_difference(
            test, y=y_test, scores=scores, baseline_scores=rule_scores,
            repetitions=bootstrap_repetitions, seed=seed + 1,
        )
        metrics["recall_at_fixed_precision"] = metrics["recall"]
        metrics["fixed_precision_target"] = precision_target
        metrics["stockouts_caught_share"] = metrics["recall"]
        test_metric_results[name] = metrics

    selected_metrics = test_metric_results[chosen_model_name]
    group_train = frame.loc[
        (frame["group_split"] == "train")
        & (frame["time_split"] == "train")
        & frame["target"].notna()
    ].copy()
    group_validation = frame.loc[
        (frame["group_split"] == "train")
        & (frame["time_split"] == "validation")
        & frame["target"].notna()
    ].copy()
    group_test_summary = (
        metadata["split_boundaries"].get("unseen_group", {}).get("test", {})
    )
    group_test_count = int(group_test_summary.get("positive_count", -1))
    group_test_guard = TestSetAccessGuard(
        lambda: frame.loc[
            (frame["group_split"] == "test") & frame["target"].notna()
        ].copy()
    )
    unseen_recall: float | None = None
    group_result: dict[str, Any] = {
        "status": "not computed",
        "test_rows": group_test_summary.get("row_count"),
    }
    if (
        not group_train.empty
        and not group_validation.empty
        and group_test_count >= minimum_split_positives
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
        group_calibrator = None
        if len(np.unique(group_y_validation)) > 1 and len(group_y_validation) >= 20:
            group_calibrator = IsotonicRegression(out_of_bounds="clip").fit(
                group_val_scores, group_y_validation
            )
            group_val_scores = group_calibrator.predict(group_val_scores)
        group_threshold, group_threshold_detail = _threshold_for_precision(
            group_y_validation, group_val_scores, precision_target
        )
        unseen_test = group_test_guard.evaluate_once()
        if int(pd.to_numeric(unseen_test["target"]).sum()) < minimum_split_positives:
            raise ValueError("Unseen-group test split has fewer positives than its metadata declares.")
        group_x_test, group_y_test = _split_xy(unseen_test, features)
        group_test_scores = _probabilities(group_model, group_x_test)
        if group_calibrator is not None:
            group_test_scores = group_calibrator.predict(group_test_scores)
        group_metrics = _metric_summary(group_y_test, group_test_scores, group_threshold)
        unseen_recall = group_metrics["recall"]
        group_result = {
            "status": "computed",
            "model": chosen_model_name,
            "metrics": group_metrics,
            "threshold_selection": group_threshold_detail,
            "groups": sorted(unseen_test["facility_id"].astype(str).unique().tolist()),
            "test_access_count": group_test_guard.access_count,
        }
    else:
        group_result["reason"] = (
            "Grouped train, validation, and test partitions each require at least "
            f"{minimum_split_positives} positives."
        )

    gate = evaluate_promotion_gate(
        is_synthetic=is_synthetic,
        time_based_split=True,
        test_metrics={
            "rule_baseline": test_metric_results["rule_baseline"],
            "selected_model": selected_metrics,
        },
        gate_diagnostics={
            "unseen_recall": unseen_recall,
            "leakage_warnings": leakage_warnings,
        },
    )

    lead_time = {
        "status": "not computed",
        "reason": "The feature table stores window labels but not the observed event date within each label window.",
        "rule_baseline_stockouts_caught_share": test_metric_results["rule_baseline"]["recall"],
        "selected_model_stockouts_caught_share": selected_metrics["recall"],
        "mean_periods_early": None,
        "median_periods_early": None,
    }
    model_version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    artifact_dir = _create_artifact_directory(model_root, model_version)
    training_dates = pd.to_datetime(train["date"])
    metadata_out = {
        "notice": "SYNTHETIC - not evidence of real-world performance" if is_synthetic else "Model evaluation artifact",
        "model_version": model_version,
        "time_based_split": True,
        "test_metrics": selected_metrics,
        "all_test_metrics": test_metric_results,
        "training_date_range": {
            "start": training_dates.min().date().isoformat(),
            "end": training_dates.max().date().isoformat(),
        },
        "data_hash": metadata["dataset_hash"],
        "feature_dataset_id": metadata["build_id"],
        "feature_list": features,
        "horizon_days": int(metadata["horizon"]),
        "data_frequency": metadata["frequency"],
        "is_synthetic": is_synthetic,
        "threshold": thresholds[chosen_model_name],
        "threshold_selection": threshold_selection[chosen_model_name],
        "gate_results": gate,
        "promotion_diagnostics": {
            "unseen_recall": unseen_recall,
            "leakage_warnings": leakage_warnings,
        },
        "selected_model": chosen_model_name,
        "model_validated": bool(gate["model_validated"] and not is_synthetic),
        "library_versions": {"python": platform.python_version(), "pandas": pd.__version__, "scikit_learn": sklearn.__version__},
        "random_seed": seed,
        "git_commit": _git_commit(),
        "calibration": calibration_report[chosen_model_name],
        "feature_builder_state": metadata["feature_builder_state"],
        "validation_only_tuning": parameters,
        "test_access_count": test_guard.access_count,
        "unseen_group": {
            "group_column": metadata.get("group_column"),
            "test_rows": group_test_summary.get("row_count"),
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
    metadata_path = artifact_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata_out, indent=2, allow_nan=False, default=_json_default), encoding="utf-8")
    report = {
        "notice": metadata_out["notice"],
        "is_synthetic": is_synthetic,
        "interpretation": (
            "This run uses synthetic data designed to test signal recovery. It is not evidence of real-world performance."
            if is_synthetic else
            "This is a single held-out evaluation under the recorded data and split design. It does not establish causal impact or deployment readiness."
        ),
        "test_metrics": test_metric_results,
        "calibration": calibration_report,
        "label_prevalence": metadata.get("label_prevalence"),
        "feature_availability": metadata.get("feature_availability", {}),
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate models on a Phase 3 feature dataset.")
    parser.add_argument("feature_dataset_id", help="Unique build ID emitted by ml.build_dataset")
    parser.add_argument("--feature-root", type=Path, default=FEATURE_ROOT)
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--precision-target", type=float, default=0.5)
    parser.add_argument("--minimum-positives", type=int, default=1)
    parser.add_argument("--minimum-split-positives", type=int, default=5)
    parser.add_argument("--minimum-group-positives", type=int, default=5)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--bootstrap-repetitions", type=int, default=200)
    args = parser.parse_args()
    artifact = train_feature_dataset(
        args.feature_dataset_id,
        feature_root=args.feature_root,
        model_root=args.model_root,
        precision_target=args.precision_target,
        minimum_positives=args.minimum_positives,
        minimum_split_positives=args.minimum_split_positives,
        minimum_group_positives=args.minimum_group_positives,
        seed=args.seed,
        bootstrap_repetitions=args.bootstrap_repetitions,
    )
    artifact_metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
    prefix = _log_prefix(bool(artifact_metadata["is_synthetic"]))
    print(f"{prefix}Artifact saved: {artifact}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
