from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def target_leakage_diagnostics(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    feature_lineage: dict[str, dict[str, object]] | None = None,
    correlation_threshold: float = 0.95,
) -> dict[str, Any]:
    if "target" not in labels:
        raise ValueError("labels must contain target")
    if not 0 < correlation_threshold <= 1:
        raise ValueError("correlation_threshold must be in (0, 1]")
    aligned = labels.loc[features.index]
    target = pd.to_numeric(aligned["target"], errors="coerce")
    eligible = target.notna()
    y = target.loc[eligible].astype(int)
    correlations: list[dict[str, object]] = []
    aucs: list[dict[str, object]] = []
    if y.nunique() > 1:
        for column in features.columns:
            if column in {"facility_id", "item_id", "date", "is_synthetic"}:
                continue
            values = pd.to_numeric(features.loc[eligible, column], errors="coerce")
            valid = values.notna()
            if valid.sum() < 3 or values.loc[valid].nunique() < 2:
                continue
            correlation = float(values.loc[valid].corr(y.loc[valid]))
            if abs(correlation) > correlation_threshold:
                correlations.append({"feature": column, "correlation": correlation})
            auc = float(roc_auc_score(y.loc[valid], values.loc[valid]))
            aucs.append({"feature": column, "auc": max(auc, 1 - auc)})

    future_stock_features = []
    for name, definition in (feature_lineage or {}).items():
        source = str(definition.get("source", ""))
        offset = int(definition.get("max_time_offset", 0))
        if "stock_on_hand" in source and offset > 0:
            future_stock_features.append(name)
            warnings.warn(
                f"Feature '{name}' derives from stock_on_hand at t+{offset}; this is target leakage.",
                RuntimeWarning,
                stacklevel=2,
            )

    aucs.sort(key=lambda item: str(item["feature"]))
    return {
        "high_correlations": correlations,
        "single_feature_auc": aucs,
        "days_of_cover_auc": next(
            (
                item["auc"]
                for item in aucs
                if item["feature"] in {"days_of_cover", "months_of_stock"}
            ),
            None,
        ),
        "probable_leak_or_trivial_rule": [
            item for item in aucs if float(item["auc"]) > 0.95
        ],
        "future_stock_feature_warnings": future_stock_features,
    }


def assert_no_high_target_correlations(
    diagnostics: dict[str, Any],
    *,
    threshold: float = 0.95,
) -> None:
    failures = [
        item for item in diagnostics["high_correlations"]
        if abs(float(item["correlation"])) > threshold
    ]
    if failures:
        raise AssertionError(f"Highly target-correlated features detected: {failures}")
