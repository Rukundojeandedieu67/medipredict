from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_GATE_LIMITS = {
    "maximum_brier_score": 0.25,
    "maximum_unseen_recall_drop": 0.10,
}


def evaluate_promotion_gate(
    *,
    is_synthetic: bool,
    time_based_split: bool,
    test_metrics: dict[str, Any],
    gate_diagnostics: dict[str, Any],
    provenance_status: str = "uploaded_unverified",
    dataset_hash: str | None = None,
    verified_dataset_hash: str | None = None,
    limits: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return each promotion criterion explicitly; synthetic artifacts never pass."""
    configured = {**DEFAULT_GATE_LIMITS, **(limits or {})}
    baseline = test_metrics.get("rule_baseline", {})
    model = test_metrics.get("selected_model", {})
    pr = model.get("pr_auc")
    baseline_pr = baseline.get("pr_auc")
    difference_ci = model.get("pr_auc_difference_vs_rule_ci")
    recall = model.get("recall_at_fixed_precision")
    baseline_recall = baseline.get("recall_at_fixed_precision")
    precision_target = model.get("fixed_precision_target")
    baseline_precision_target = baseline.get("fixed_precision_target")
    comparable_precision_operating_point = bool(
        model.get("precision_target_attained_on_validation") is True
        and baseline.get("precision_target_attained_on_validation") is True
        and isinstance(precision_target, (int, float))
        and precision_target == baseline_precision_target
    )
    brier = model.get("brier")
    unseen_recall = gate_diagnostics.get("unseen_recall")
    time_recall = model.get("recall")
    history_count = gate_diagnostics.get("history_period_count")
    minimum_history = gate_diagnostics.get("minimum_history_periods")
    split_positives = gate_diagnostics.get("positive_counts_per_split", {})
    minimum_positives = gate_diagnostics.get("minimum_positives_per_split")
    facility_count = gate_diagnostics.get("distinct_facilities")
    minimum_facilities = gate_diagnostics.get("minimum_facilities")
    support_ok = bool(
        isinstance(history_count, int)
        and isinstance(minimum_history, int)
        and history_count >= minimum_history
        and isinstance(split_positives, dict)
        and isinstance(minimum_positives, int)
        and all(
            isinstance(split_positives.get(name), int)
            and split_positives[name] >= minimum_positives
            for name in ("train", "validation", "test")
        )
        and isinstance(facility_count, int)
        and isinstance(minimum_facilities, int)
        and facility_count >= minimum_facilities
    )
    verified_provenance = bool(
        not is_synthetic
        and provenance_status == "verified"
        and isinstance(dataset_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", dataset_hash)
        and dataset_hash == verified_dataset_hash
    )
    criteria = {
        "real_data": not is_synthetic,
        "verified_provenance": verified_provenance,
        "time_based_split": bool(time_based_split),
        "test_pr_auc_beats_rule_with_ci": bool(
            isinstance(pr, (int, float))
            and isinstance(baseline_pr, (int, float))
            and pr > baseline_pr
            and isinstance(difference_ci, (list, tuple))
            and len(difference_ci) == 2
            and difference_ci[0] > 0
        ),
        "recall_beats_rule_at_fixed_precision": bool(
            comparable_precision_operating_point
            and
            isinstance(recall, (int, float))
            and isinstance(baseline_recall, (int, float))
            and recall > baseline_recall
        ),
        "comparable_precision_operating_point": comparable_precision_operating_point,
        "calibration_within_limit": bool(
            isinstance(brier, (int, float))
            and brier <= configured["maximum_brier_score"]
        ),
        "unseen_facility_within_tolerance": bool(
            isinstance(unseen_recall, (int, float))
            and isinstance(time_recall, (int, float))
            and unseen_recall >= time_recall - configured["maximum_unseen_recall_drop"]
        ),
        "no_phase3_leakage_warnings": not bool(
            gate_diagnostics.get("leakage_warnings")
        ),
        "minimum_history_and_support": support_ok,
    }
    reasons = {
        "real_data": (
            "Passed: dataset is explicitly non-synthetic."
            if criteria["real_data"]
            else "Failed: synthetic data can never be promoted."
        ),
        "verified_provenance": (
            "Passed: dataset provenance is verified against the exact registered dataset hash."
            if verified_provenance
            else (
                "Failed: dataset provenance is not verified against the exact registered dataset hash."
            )
        ),
        "time_based_split": (
            "Passed: temporal split integrity was verified."
            if criteria["time_based_split"]
            else "Failed: temporal split integrity was not verified."
        ),
        "test_pr_auc_beats_rule_with_ci": (
            "Passed: PR-AUC exceeds the rule baseline and the clustered-bootstrap difference interval is above zero."
            if criteria["test_pr_auc_beats_rule_with_ci"]
            else "Failed: PR-AUC improvement over the rule baseline is absent or its clustered-bootstrap interval includes zero."
        ),
        "recall_beats_rule_at_fixed_precision": (
            "Passed: recall is higher at the same validation-selected precision target."
            if criteria["recall_beats_rule_at_fixed_precision"]
            else "Failed: recall did not improve at a comparable precision operating point."
        ),
        "comparable_precision_operating_point": (
            "Passed: model and rule thresholds attained the same validation precision target."
            if criteria["comparable_precision_operating_point"]
            else "Failed: model and rule thresholds do not share an attained validation precision target."
        ),
        "calibration_within_limit": (
            f"Passed: Brier score is at or below {configured['maximum_brier_score']}."
            if criteria["calibration_within_limit"]
            else f"Failed: Brier score is missing or above {configured['maximum_brier_score']}."
        ),
        "unseen_facility_within_tolerance": (
            f"Passed: unseen-group recall is within {configured['maximum_unseen_recall_drop']} of temporal recall."
            if criteria["unseen_facility_within_tolerance"]
            else f"Failed: unseen-group recall is missing or below temporal recall by more than {configured['maximum_unseen_recall_drop']}."
        ),
        "no_phase3_leakage_warnings": (
            "Passed: no Phase 3 leakage warnings were recorded."
            if criteria["no_phase3_leakage_warnings"]
            else f"Failed: leakage warnings were recorded: {gate_diagnostics.get('leakage_warnings')}."
        ),
        "minimum_history_and_support": (
            "Passed: required history, positive counts in all temporal splits, and facility count are met."
            if support_ok
            else (
                "Failed: required history, minimum positives in each temporal split, "
                "or minimum distinct facility count is missing or unmet. "
                f"Observed periods={history_count}, split positives={split_positives}, "
                f"facilities={facility_count}."
            )
        ),
    }
    failed = [name for name, passed in criteria.items() if not passed]
    return {
        "model_validated": not failed,
        "criteria": criteria,
        "reasons": reasons,
        "failed_criteria": failed,
        "limits": configured,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-evaluate the recorded promotion gate for a Phase 4 artifact."
    )
    parser.add_argument("metadata", type=Path, help="Path to the artifact metadata.json")
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    required = ("is_synthetic", "time_based_split", "all_test_metrics", "promotion_diagnostics")
    missing = [field for field in required if field not in metadata]
    if missing:
        raise ValueError(f"Artifact metadata is missing: {', '.join(missing)}")
    selected_name = metadata.get("selected_model")
    if selected_name not in metadata.get("all_test_metrics", {}):
        raise ValueError("Artifact metadata does not identify a selected model.")
    gate = evaluate_promotion_gate(
        is_synthetic=metadata["is_synthetic"],
        time_based_split=metadata["time_based_split"],
        test_metrics={
            "rule_baseline": metadata["all_test_metrics"].get("rule_baseline", {}),
            "selected_model": metadata["all_test_metrics"][selected_name],
        },
        gate_diagnostics=metadata["promotion_diagnostics"],
        provenance_status=metadata.get("provenance_status", "uploaded_unverified"),
        dataset_hash=metadata.get("data_hash"),
        verified_dataset_hash=metadata.get("verified_dataset_hash"),
    )
    prefix = (
        "SYNTHETIC - not evidence of real-world performance | "
        if metadata["is_synthetic"] else ""
    )
    print(
        prefix
        + json.dumps(
            {
                "model_version": metadata.get("model_version"),
                "model_validated": gate["model_validated"],
                "gate_results": gate,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
