from __future__ import annotations

import argparse
import json
from pathlib import Path
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
    limits: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return each promotion criterion explicitly; synthetic artifacts never pass."""
    configured = {**DEFAULT_GATE_LIMITS, **(limits or {})}
    baseline = test_metrics.get("rule_baseline", {})
    model = test_metrics.get("selected_model", {})
    pr = model.get("pr_auc")
    baseline_pr = baseline.get("pr_auc")
    difference_ci = model.get("pr_auc_difference_vs_rule_ci")
    recall = model.get("recall")
    baseline_recall = baseline.get("recall")
    brier = model.get("brier")
    unseen_recall = gate_diagnostics.get("unseen_recall")
    time_recall = model.get("recall")
    criteria = {
        "real_data": not is_synthetic,
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
            isinstance(recall, (int, float))
            and isinstance(baseline_recall, (int, float))
            and recall > baseline_recall
        ),
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
    }
    failed = [name for name, passed in criteria.items() if not passed]
    return {
        "model_validated": not failed,
        "criteria": criteria,
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
