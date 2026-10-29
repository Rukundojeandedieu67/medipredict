from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

import pandas as pd

from backend.app.config import ROOT, settings
from backend.app.provenance import resolve_provenance
from backend.app.validation import ValidationConfig, validate_inventory_csv
from .features import DEFAULT_CALENDAR_PATH, FeatureBuilder
from .labels import LabelMode, build_labels, label_prevalence
from .leakage import target_leakage_diagnostics
from .missingness import profile_inventory_missingness
from .periods import DataFrequency, parse_boolean
from .splits import assign_time_splits, grouped_unseen_split, time_based_split

DATASET_ID_PATTERN = re.compile(r"^v1-\d{8}T\d{6}Z-[0-9a-f]{32}$")
DEFAULT_OUTPUT_ROOT = ROOT / "ml" / "artifacts" / "feature_tables"


def _load_registered_dataset(
    dataset_id: str,
    uploads_root: Path,
) -> tuple[pd.DataFrame, dict[str, object], str]:
    if not DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ValueError("Invalid training-upload dataset ID.")
    dataset_dir = uploads_root / "v1" / dataset_id
    metadata_path = dataset_dir / "metadata.json"
    data_path = dataset_dir / "data.csv"
    if not metadata_path.is_file() or not data_path.is_file():
        raise FileNotFoundError(f"Registered dataset '{dataset_id}' is missing data or metadata.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("dataset_id") != dataset_id:
        raise ValueError("Dataset registry ID does not match its metadata.")
    raw_bytes = data_path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if digest != metadata.get("sha256"):
        raise ValueError("Dataset content hash does not match the training-upload registry.")
    frame = pd.read_csv(data_path, dtype=str, keep_default_na=False)
    if metadata.get("row_count") != len(frame):
        raise ValueError("Dataset row count does not match the training-upload registry.")
    if "is_synthetic" not in frame:
        raise ValueError("Registered dataset is missing its required is_synthetic column.")
    flags = frame["is_synthetic"].str.strip().str.casefold()
    if not flags.isin(("true", "false")).all():
        raise ValueError("Registered dataset contains unknown synthetic provenance.")
    synthetic_values = flags.map({"true": True, "false": False})
    expected_synthetic = (
        bool(synthetic_values.iloc[0])
        if synthetic_values.nunique() == 1
        else None
    )
    if metadata.get("is_synthetic") is not expected_synthetic:
        raise ValueError("Dataset synthetic flag does not match the training-upload registry.")
    data_source = metadata.get("data_source")
    if data_source not in ("uploaded", "synthetic_generated"):
        raise ValueError("Dataset registry data_source is not supported.")
    if data_source == "synthetic_generated" and expected_synthetic is not True:
        raise ValueError("Generated synthetic datasets must be marked is_synthetic=true.")
    return frame, metadata, digest





def _table(rows: list[dict[str, object]], columns: tuple[str, ...]) -> str:
    if not rows:
        return "_No rows._"
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def build_dataset(
    dataset_id: str,
    *,
    frequency: DataFrequency | None = None,
    horizon: int | None = None,
    label_mode: LabelMode = "new_stockout",
    group_column: str = "facility_id",
    minimum_records_per_facility_item: int | None = None,
    minimum_facility_items: int | None = None,
    minimum_positives: int = 1,
    uploads_root: Path | None = None,
    output_root: Path | None = None,
    calendar_path: Path | None = None,
) -> Path:
    source_root = uploads_root or settings.uploads_path
    raw, registry, digest = _load_registered_dataset(dataset_id, source_root)
    provenance = resolve_provenance(dataset_id, source_root)
    registered_frequency = str(registry.get("data_frequency", "daily"))
    data_frequency = frequency or registered_frequency
    if registered_frequency != data_frequency:
        raise ValueError(
            f"Requested {data_frequency} frequency conflicts with registry frequency {registered_frequency}."
        )
    if data_frequency not in ("daily", "monthly"):
        raise ValueError("Dataset registry contains an unsupported data frequency.")
    selected_horizon = horizon if horizon is not None else (14 if data_frequency == "daily" else 1)
    if selected_horizon not in (1, 2) and data_frequency == "monthly":
        raise ValueError("Monthly horizon must be 1 or 2 months.")
    if selected_horizon < 1:
        raise ValueError("Horizon must be positive.")
    config = ValidationConfig(
        minimum_records_per_facility_item=(
            (
                settings.training_min_records
                if data_frequency == "daily"
                else settings.training_min_records_monthly
            )
            if minimum_records_per_facility_item is None
            else minimum_records_per_facility_item
        ),
        minimum_facility_items=(
            settings.training_min_facility_items
            if minimum_facility_items is None
            else minimum_facility_items
        ),
        data_frequency=data_frequency,
    )
    validation = validate_inventory_csv(raw, purpose="training", config=config)
    if not validation["valid"]:
        raise ValueError(
            "Registered dataset failed training validation: "
            + "; ".join(issue["message"] for issue in validation["errors"][:5])
        )
    if registry.get("date_range") != validation["date_range"]:
        raise ValueError("Dataset date range does not match the training-upload registry.")

    labels = build_labels(
        raw,
        horizon=selected_horizon,
        frequency=data_frequency,
        label_mode=label_mode,
    )
    labeled = labels.reset_index(drop=True)
    split = time_based_split(
        labeled,
        horizon=selected_horizon,
        frequency=data_frequency,
        minimum_positives=minimum_positives,
    )
    try:
        grouped = grouped_unseen_split(
            labeled,
            group_column=group_column,  # type: ignore[arg-type]
            minimum_positives=minimum_positives,
        )
    except ValueError as exc:
        raise ValueError(f"Unseen-{group_column} split could not be produced: {exc}") from exc

    train_period_end = pd.Period(
        split["boundaries"]["train_period_end"],
        freq="D" if data_frequency == "daily" else "M",
    )
    source_periods = pd.to_datetime(raw["date"], format="%Y-%m-%d").dt.to_period(
        "D" if data_frequency == "daily" else "M"
    )
    train_mask = source_periods.le(train_period_end)
    training_rows = raw.loc[train_mask].copy()
    builder = FeatureBuilder(
        frequency=data_frequency,
        horizon=selected_horizon,
        calendar_path=calendar_path,
    ).fit(training_rows)
    features = builder.transform(raw)
    feature_rows = features.reset_index(drop=True)
    output = feature_rows.merge(
        labeled[[
            "facility_id", "item_id", "date", "target", "label_status",
            "label_window_start", "label_window_end", "label_event_date",
            "label_event_offset",
        ]],
        on=["facility_id", "item_id", "date"],
        how="left",
        validate="one_to_one",
    )

    output["time_split"] = assign_time_splits(
        output, split["boundaries"], frequency=data_frequency
    )
    held_out_groups = set(grouped["boundaries"]["test_groups"])
    output["group_split"] = output[group_column].astype(str).map(
        lambda value: "test" if value in held_out_groups else "train"
    )
    prevalence = label_prevalence(labels)
    missingness = profile_inventory_missingness(raw, frequency=data_frequency)
    diagnostic_rows = output.loc[
        output["time_split"].isin(("train", "validation"))
    ]
    diagnostic_rows = diagnostic_rows.loc[diagnostic_rows["target"].notna()]
    diagnostics = target_leakage_diagnostics(
        diagnostic_rows[builder.feature_list],
        diagnostic_rows[["target"]],
        feature_lineage=builder.feature_lineage,
    )
    availability = builder.availability_report(features)
    synthetic_flags = raw["is_synthetic"].map(parse_boolean)
    if synthetic_flags.isna().any() or synthetic_flags.nunique() != 1:
        raise ValueError("A feature dataset must have one consistent is_synthetic value for every row.")
    contains_synthetic = bool(synthetic_flags.iloc[0])
    created = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version = f"v1-{created}-{uuid.uuid4().hex}"
    destination = (output_root or DEFAULT_OUTPUT_ROOT) / dataset_id / version
    destination.mkdir(parents=True, exist_ok=False)
    features_path = destination / "features.csv"
    metadata_path = destination / "metadata.json"
    report_path = destination / "report.md"
    metadata = {
        "notice": (
            "SYNTHETIC - not evidence of real-world performance"
            if contains_synthetic
            else "Feature dataset construction metadata"
        ),
        "dataset_id": dataset_id,
        "dataset_hash": digest,
        "data_source": registry["data_source"],
        "provenance_status": provenance["provenance_status"],
        "verification": provenance["verification"],
        "verified_dataset_hash": (
            provenance["verification"]["dataset_sha256"]
            if provenance["provenance_status"] == "verified"
            and provenance["verification"] is not None
            else None
        ),
        "build_id": version,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "row_count": len(output),
        "frequency": data_frequency,
        "horizon": selected_horizon,
        "label_mode": label_mode,
        "feature_list": builder.feature_list,
        "feature_availability": availability,
        "feature_builder_state": builder.state_dict(),
        "is_synthetic": contains_synthetic,
        "split_boundaries": {
            "time_based": split["boundaries"],
            "unseen_group": grouped["boundaries"],
        },
        "label_prevalence": prevalence,
        "source_missingness": missingness,
        "leakage_diagnostics": diagnostics,
        "feature_lineage": builder.feature_lineage,
        "validation": validation,
        "group_column": group_column,
    }
    output.to_csv(features_path, index=False)
    feature_table_sha256 = hashlib.sha256(features_path.read_bytes()).hexdigest()
    metadata["feature_table_sha256"] = feature_table_sha256
    metadata["feature_table_row_count"] = len(output)
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    report = _render_report(metadata)
    report_path.write_text(report, encoding="utf-8")
    return destination


def _render_report(metadata: dict[str, object]) -> str:
    title = (
        "SYNTHETIC - not evidence of real-world performance"
        if metadata["is_synthetic"]
        else "Feature dataset preparation report"
    )
    prevalence = metadata["label_prevalence"]
    overall = prevalence["overall"]  # type: ignore[index]
    groups = []
    for column in ("facility_type", "district", "item_id"):
        for row in prevalence[column]:  # type: ignore[index]
            groups.append({"dimension": column, **row})
    availability = [
        {"feature": name, **values}
        for name, values in metadata["feature_availability"].items()  # type: ignore[union-attr]
    ]
    leakage = metadata["leakage_diagnostics"]
    leak_rows = leakage["single_feature_auc"]  # type: ignore[index]
    return "\n".join(
        (
            f"# {title}",
            "",
            "This report describes dataset construction only. It contains no trained-model evaluation.",
            "",
            f"- Dataset ID: `{metadata['dataset_id']}`",
            f"- SHA-256: `{metadata['dataset_hash']}`",
            f"- Data frequency: `{metadata['frequency']}`",
            f"- Horizon: `{metadata['horizon']}` native periods",
            f"- Label mode: `{metadata['label_mode']}`",
            f"- Feature rows: {metadata['row_count']}",
            f"- Labeled rows: {overall['rows']}",
            f"- Positive labels: {overall['positives']}",
            f"- Label prevalence: {overall['prevalence']}",
            "",
            "## Label prevalence by group",
            "",
            _table(groups, ("dimension", "value", "rows", "positives", "prevalence")),
            "",
            "## Feature availability",
            "",
            _table(
                availability,
                ("feature", "available_rows", "total_rows", "availability_share", "missing_reason"),
            ),
            "",
            "## Source missingness by facility",
            "",
            "Missing periods and explicit missing cells are separate. Missing periods are counted only within each facility-item's observed date range; zero stock/consumption is not missing. This report does not impute or create rows.",
            "",
            "```json",
            json.dumps(metadata["source_missingness"], indent=2),
            "```",
            "",
            "## Time-based split",
            "",
            "```json",
            json.dumps(metadata["split_boundaries"]["time_based"], indent=2),  # type: ignore[index]
            "```",
            "",
            "## Unseen-group split",
            "",
            "```json",
            json.dumps(metadata["split_boundaries"]["unseen_group"], indent=2),  # type: ignore[index]
            "```",
            "",
            "## Single-feature leakage diagnostics",
            "",
            "These diagnostics are not model performance results.",
            "",
            _table(leak_rows, ("feature", "auc")),
            "",
            f"- Days/months of stock single-feature AUC: `{leakage['days_of_cover_auc']}`",
            f"- High-AUC probable leak/trivial-rule features: `{leakage['probable_leak_or_trivial_rule']}`",
            f"- Future-stock feature warnings: `{leakage['future_stock_feature_warnings']}`",
            "",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build point-in-time features and labels from a registered upload.")
    parser.add_argument("dataset_id", help="ID returned by /api/v1/data/training-upload")
    parser.add_argument("--frequency", choices=("daily", "monthly"))
    parser.add_argument("--horizon", type=int)
    parser.add_argument("--label-mode", choices=("new_stockout", "any_stockout_in_window"), default="new_stockout")
    parser.add_argument("--group-by", choices=("facility_id", "district"), default="facility_id")
    parser.add_argument("--minimum-records-per-facility-item", type=int)
    parser.add_argument("--minimum-facility-items", type=int)
    parser.add_argument("--minimum-positives", type=int, default=1)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR_PATH)
    args = parser.parse_args()
    output = build_dataset(
        args.dataset_id,
        frequency=args.frequency,
        horizon=args.horizon,
        label_mode=args.label_mode,
        group_column=args.group_by,
        minimum_records_per_facility_item=args.minimum_records_per_facility_item,
        minimum_facility_items=args.minimum_facility_items,
        minimum_positives=args.minimum_positives,
        output_root=args.output_root,
        calendar_path=args.calendar,
    )
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    prefix = (
        "SYNTHETIC - not evidence of real-world performance | "
        if metadata["is_synthetic"]
        else ""
    )
    print(f"{prefix}Feature dataset saved: {output}")


if __name__ == "__main__":
    main()
