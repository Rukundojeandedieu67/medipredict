from __future__ import annotations

import asyncio
from datetime import date, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException, UploadFile

from backend.app import main
from backend.app.config import ROOT
from backend.app.validation import ValidationConfig, validate_inventory_csv
from ml.features import FeatureBuilder
from ml.labels import build_labels, label_prevalence
from ml.leakage import assert_no_high_target_correlations, target_leakage_diagnostics
from ml.splits import grouped_unseen_split, time_based_split


def _observations(
    *,
    rows: int = 80,
    frequency: str = "daily",
    facilities: int = 1,
    seed: int = 44,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    result = []
    start = date(2025, 1, 1)
    for facility in range(facilities):
        for index in range(rows):
            if frequency == "daily":
                observed_date = start + timedelta(days=index)
            else:
                month = (start.month - 1 + index) % 12 + 1
                year = start.year + (start.month - 1 + index) // 12
                observed_date = date(year, month, 1)
            stock_out = bool(rng.random() < 0.12)
            result.append(
                {
                    "facility_id": f"FAC-{facility}",
                    "item_id": "ITEM-1",
                    "date": observed_date.isoformat(),
                    "stock_on_hand": 0 if stock_out else int(rng.integers(20, 100)),
                    "units_consumed": int(rng.integers(1, 15)),
                    "units_received": int(rng.choice([0, 0, 5, 15])),
                    "is_synthetic": True,
                    "facility_type": "Health Centre",
                    "district": f"DIST-{facility % 2}",
                }
            )
    return pd.DataFrame(result)


def _simple_calendar(
    path, *, coverage=(2026,), holidays=None, umuganda=None,
    commemoration=None, umuganda_rule_enabled=True,
):
    path.write_text(
        json.dumps(
            {
                "source_notes": ["Test-only calendar fixture; not a Rwanda calendar source."],
                "calendar_coverage_years": list(coverage),
                "umuganda_last_saturday_enabled": umuganda_rule_enabled,
                "seasons": [
                    {"name": "long_rains", "months": [3, 4, 5]},
                    {"name": "short_dry", "months": [6, 7, 8]},
                    {"name": "short_rains", "months": [9, 10, 11]},
                    {"name": "long_dry", "months": [12, 1, 2]},
                ],
                "umuganda_weeks": umuganda or [],
                "national_commemoration_periods": commemoration or [],
                "public_holidays": holidays or [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_daily_labels_use_only_future_window_and_exclude_current_stockout():
    rows = pd.DataFrame(
        [
            ("F", "I", "2026-01-01", 10),
            ("F", "I", "2026-01-02", 12),
            ("F", "I", "2026-01-03", 0),
            ("F", "I", "2026-01-04", 15),
        ],
        columns=["facility_id", "item_id", "date", "stock_on_hand"],
    )

    labels = build_labels(rows, horizon=1, frequency="daily")

    assert labels.loc[("F", "I", pd.Timestamp("2026-01-01")), "target"] == 0
    assert labels.loc[("F", "I", pd.Timestamp("2026-01-02")), "target"] == 1
    assert pd.isna(labels.loc[("F", "I", pd.Timestamp("2026-01-03")), "target"])
    assert labels.loc[("F", "I", pd.Timestamp("2026-01-03")), "label_status"] == "excluded_current_stockout"
    assert pd.isna(labels.loc[("F", "I", pd.Timestamp("2026-01-04")), "target"])
    assert labels.loc[("F", "I", pd.Timestamp("2026-01-04")), "label_status"] == "unobserved_window"
    prevalence = label_prevalence(labels)
    assert prevalence["overall"] == {"rows": 2, "positives": 1, "prevalence": 0.5}
    assert prevalence["facility_type"] == []


def test_any_stockout_mode_and_missing_periods_are_explicit():
    rows = pd.DataFrame(
        [
            ("F", "I", "2026-01-01", 10),
            ("F", "I", "2026-01-03", 0),
            ("F", "I", "2026-01-04", 12),
        ],
        columns=["facility_id", "item_id", "date", "stock_on_hand"],
    )
    labels = build_labels(rows, horizon=2, frequency="daily")

    assert labels.loc[("F", "I", pd.Timestamp("2026-01-01")), "label_status"] == "unobserved_period"
    assert pd.isna(labels.loc[("F", "I", pd.Timestamp("2026-01-01")), "target"])
    any_labels = build_labels(
        rows,
        horizon=1,
        frequency="daily",
        label_mode="any_stockout_in_window",
    )
    assert any_labels.loc[("F", "I", pd.Timestamp("2026-01-03")), "target"] == 0

    later_rows = pd.DataFrame(
        [
            ("F", "I", "2026-01-01", 10),
            ("F", "I", "2026-01-05", 10),
        ],
        columns=["facility_id", "item_id", "date", "stock_on_hand"],
    )
    later = build_labels(later_rows, horizon=2, frequency="daily")
    assert later.loc[("F", "I", pd.Timestamp("2026-01-01")), "label_status"] == "unobserved_period"


def test_monthly_label_uses_stock_out_days_and_monthly_horizon():
    rows = pd.DataFrame(
        [
            ("F", "I", "2026-01-31", 20, 0),
            ("F", "I", "2026-02-28", 20, 0),
            ("F", "I", "2026-03-31", 20, 2),
            ("F", "I", "2026-04-30", 20, 0),
        ],
        columns=["facility_id", "item_id", "date", "stock_on_hand", "stock_out_days"],
    )

    labels = build_labels(rows, horizon=2, frequency="monthly")

    assert labels.loc[("F", "I", pd.Timestamp("2026-01-31")), "target"] == 1
    assert labels.loc[("F", "I", pd.Timestamp("2026-02-28")), "target"] == 1
    assert labels.loc[("F", "I", pd.Timestamp("2026-03-31")), "label_status"] == "excluded_current_stockout"
    assert pd.isna(labels.loc[("F", "I", pd.Timestamp("2026-04-30")), "target"])


def test_monthly_validator_checks_stock_out_days_and_missing_months():
    rows = pd.DataFrame(
        [
            {
                "facility_id": "F",
                "item_id": "I",
                "date": "2026-01-31",
                "stock_on_hand": "10",
                "units_consumed": "2",
                "units_received": "0",
                "is_synthetic": "true",
                "stock_out_days": "32",
            },
            {
                "facility_id": "F",
                "item_id": "I",
                "date": "2026-03-31",
                "stock_on_hand": "10",
                "units_consumed": "2",
                "units_received": "0",
                "is_synthetic": "true",
                "stock_out_days": "0",
            },
        ]
    )
    report = validate_inventory_csv(
        rows,
        purpose="assessment",
        config=ValidationConfig(
            minimum_records_per_facility_item=1,
            minimum_facility_items=1,
            data_frequency="monthly",
        ),
    )

    assert report["data_frequency"] == "monthly"
    assert any(issue["code"] == "INVALID_STOCK_OUT_DAYS" for issue in report["errors"])
    assert any(issue["code"] == "DATE_GAPS" for issue in report["warnings"])

    duplicate_month = pd.concat([rows.iloc[[0]], rows.iloc[[0]].assign(date="2026-01-15")], ignore_index=True)
    duplicate_report = validate_inventory_csv(
        duplicate_month,
        purpose="assessment",
        config=ValidationConfig(
            minimum_records_per_facility_item=1,
            minimum_facility_items=1,
            data_frequency="monthly",
        ),
    )
    assert any(
        issue["code"] == "DUPLICATE_FACILITY_ITEM_DATE"
        for issue in duplicate_report["errors"]
    )


def test_monthly_csv_is_not_returned_as_a_daily_rule_based_assessment(monkeypatch):
    monkeypatch.setattr(main.settings, "data_frequency", "monthly")
    content = (
        "facility_id,item_id,date,stock_on_hand,units_consumed,units_received,is_synthetic\n"
        "FAC-1,ITEM-1,2026-01-31,20,4,0,true\n"
    )
    upload = UploadFile(filename="monthly.csv", file=io.BytesIO(content.encode("utf-8")))

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.assess_csv(upload))

    assert error.value.status_code == 422
    assert "daily-frequency data only" in error.value.detail


def test_future_invariance_and_point_in_time_label_window():
    source = _observations(rows=70)
    builder = FeatureBuilder(frequency="daily", horizon=2).fit(source.iloc[:50])
    baseline = builder.transform(source)
    target_date = pd.Timestamp(source.iloc[35]["date"])
    changed = source.copy()
    future = pd.to_datetime(changed["date"]) > target_date
    changed.loc[future, "stock_on_hand"] = 1_000_000
    changed.loc[future, "units_consumed"] = 999_999
    changed.loc[future, "units_received"] = 123_456
    altered = builder.transform(changed)
    key = ("FAC-0", "ITEM-1", target_date)
    pd.testing.assert_series_equal(
        baseline.loc[key, builder.feature_list],
        altered.loc[key, builder.feature_list],
        check_names=False,
    )

    labels = build_labels(source, horizon=2, frequency="daily")
    observed = labels["target"].notna()
    assert (labels.loc[observed, "label_window_start"] == labels.index.get_level_values("t")[observed]).all()
    assert (labels.loc[observed, "label_window_end"] > labels.index.get_level_values("t")[observed]).all()
    assert set(builder.feature_lineage[name]["max_time_offset"] for name in builder.feature_list) == {0}
    assert not {"target", "label_window_end"}.intersection(builder.feature_list)


def test_feature_builder_requires_fit_and_emits_unique_observation_keys():
    source = _observations(rows=50)
    builder = FeatureBuilder(frequency="daily")
    with pytest.raises(RuntimeError, match="fit"):
        builder.transform(source)

    features = builder.fit(source.iloc[:30]).transform(source)

    assert features.index.names == ["facility_id", "item_id", "t"]
    assert not features.index.has_duplicates
    assert features.index.is_monotonic_increasing
    assert len(features) == len(source)
    assert features.attrs["training_period_end"] == "2025-01-30T00:00:00"


def test_safe_division_caps_cover_and_optional_inputs_have_availability():
    source = _observations(rows=40)
    source["units_consumed"] = 0
    source["reorder_level"] = 0
    source["stock_on_hand"] = 10
    builder = FeatureBuilder(frequency="daily", horizon=1).fit(source)
    features = builder.transform(source)
    latest = features.iloc[-1]
    assert pd.isna(latest["days_of_cover"])
    assert pd.isna(latest["stock_to_reorder_level_ratio"])
    assert features.attrs["feature_availability"]["rainfall_anomaly"]["available_rows"] == 0
    assert "not present or populated in training data" in features.attrs["feature_availability"]["rainfall_anomaly"]["missing_reason"]

    capped = source.copy()
    capped["units_consumed"] = 1
    capped["stock_on_hand"] = 1_000_000
    capped_features = FeatureBuilder(frequency="daily", horizon=1).fit(capped).transform(capped)
    assert capped_features.iloc[-1]["days_of_cover"] == 365


def test_monthly_features_do_not_include_daily_only_columns():
    source = _observations(rows=18, frequency="monthly")
    source["stock_out_days"] = 0
    builder = FeatureBuilder(frequency="monthly", horizon=2).fit(source.iloc[:12])
    features = builder.transform(source)

    assert "months_of_stock" in features
    assert "consumption_mean_3_months" in features
    assert "consumption_mean_12_months" in features
    assert "week_of_year" not in features
    assert "days_of_cover" not in features
    assert features.attrs["feature_availability"]["rainfall_anomaly"]["missing_reason"]

    high_stock = source.copy()
    high_stock["units_consumed"] = 1
    high_stock["stock_on_hand"] = 1_000_000
    monthly_cover = FeatureBuilder(frequency="monthly").fit(high_stock.iloc[:12]).transform(high_stock)
    assert monthly_cover.iloc[-1]["months_of_stock"] == 120


def test_configured_calendar_table_and_rwanda_season_feature(tmp_path):
    calendar = _simple_calendar(
        tmp_path / "calendar.json",
        holidays=["2026-01-08", "2026-01-12"],
        umuganda=[{"start": "2026-01-05", "end": "2026-01-07"}],
        commemoration=[{"start": "2026-01-07", "end": "2026-01-20"}],
        umuganda_rule_enabled=False,
    )
    source = _observations(rows=20)
    source["date"] = pd.date_range("2026-01-01", periods=20).strftime("%Y-%m-%d")
    builder = FeatureBuilder(
        frequency="daily",
        horizon=2,
        calendar_path=calendar,
    ).fit(source.iloc[:10])
    features = builder.transform(source)
    row = features.loc[("FAC-0", "ITEM-1", pd.Timestamp("2026-01-07"))]

    assert row["rwanda_season"] == "long_dry"
    assert bool(row["umuganda_week"]) is True
    assert bool(row["national_commemoration_period"]) is True
    assert row["public_holiday_count_next_2_days"] == 1


def test_umuganda_last_saturday_rule_and_config_toggle(tmp_path):
    source = _observations(rows=35)
    source["date"] = pd.date_range("2026-01-01", periods=35).strftime("%Y-%m-%d")
    enabled_calendar = _simple_calendar(tmp_path / "enabled.json")
    enabled = FeatureBuilder(
        frequency="daily", calendar_path=enabled_calendar
    ).fit(source.iloc[:20]).transform(source)
    assert bool(enabled.loc[("FAC-0", "ITEM-1", pd.Timestamp("2026-01-31")), "umuganda_week"])
    assert not bool(enabled.loc[("FAC-0", "ITEM-1", pd.Timestamp("2026-01-30")), "umuganda_week"])

    disabled_calendar = _simple_calendar(
        tmp_path / "disabled.json", umuganda_rule_enabled=False
    )
    disabled = FeatureBuilder(
        frequency="daily", calendar_path=disabled_calendar
    ).fit(source.iloc[:20]).transform(source)
    assert not disabled["umuganda_week"].fillna(False).any()


def test_time_splits_are_chronological_with_horizon_purge_and_positive_checks():
    dates = pd.date_range("2026-01-01", periods=50, freq="D")
    frame = pd.DataFrame(
        {
            "facility_id": "F",
            "item_id": "I",
            "date": dates,
            "target": [int(index in {3, 12, 25, 31, 37, 42, 47}) for index in range(50)],
        }
    )
    result = time_based_split(frame, horizon=2, frequency="daily")
    splits = result["splits"]
    boundaries = result["boundaries"]

    assert boundaries["purge_gap_periods"] == 2
    assert boundaries["purged_before_validation"] == ["2026-01-29", "2026-01-30"]
    assert boundaries["purged_before_test"] == ["2026-02-08", "2026-02-09"]
    assert splits["train"]["date"].max() < splits["validation"]["date"].min()
    assert splits["validation"]["date"].max() < splits["test"]["date"].min()
    assert splits["train"]["date"].max() + pd.Timedelta(days=2) < splits["validation"]["date"].min()
    assert splits["validation"]["date"].max() + pd.Timedelta(days=2) < splits["test"]["date"].min()
    assert all(summary["positive_count"] >= 1 for name, summary in boundaries.items() if name in {"train", "validation", "test"})

    frame["target"] = 0
    with pytest.raises(ValueError, match="positive labels"):
        time_based_split(frame, horizon=2, frequency="daily")


def test_unseen_facility_group_split_is_disjoint():
    source = _observations(rows=50, facilities=5)
    labels = build_labels(source, horizon=1, frequency="daily").reset_index(drop=True)
    labels["target"] = labels["target"].fillna(0).astype(int)

    result = grouped_unseen_split(labels, group_column="facility_id")

    train_groups = set(result["boundaries"]["train_groups"])
    test_groups = set(result["boundaries"]["test_groups"])
    assert train_groups.isdisjoint(test_groups)
    assert len(test_groups) == 1
    assert result["boundaries"]["test"]["positive_count"] > 0


def test_synthetic_leakage_scan_has_no_high_correlations_and_reports_future_lineage():
    source = _observations(rows=500, seed=219)
    labels = build_labels(source, horizon=1, frequency="daily")
    builder = FeatureBuilder(frequency="daily", horizon=1).fit(source.iloc[:350])
    features = builder.transform(source)

    diagnostics = target_leakage_diagnostics(
        features,
        labels,
        feature_lineage=builder.feature_lineage,
    )
    assert_no_high_target_correlations(diagnostics)
    with pytest.warns(RuntimeWarning, match="stock_on_hand at t\\+1"):
        future_diagnostic = target_leakage_diagnostics(
            features,
            labels,
            feature_lineage={"leaky": {"source": "stock_on_hand", "max_time_offset": 1}},
        )
    assert future_diagnostic["future_stock_feature_warnings"] == ["leaky"]
    assert isinstance(diagnostics["days_of_cover_auc"], (float, type(None)))
    assert diagnostics["future_stock_feature_warnings"] == []


def test_synthetic_registered_dataset_builds_versioned_outputs_and_preserves_flag(tmp_path):
    source = _observations(rows=100, facilities=5, seed=903)
    content = source.to_csv(index=False).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    dataset_id = "v1-20261016T120000Z-" + "a" * 32
    registry = tmp_path / "uploads" / "v1" / dataset_id
    registry.mkdir(parents=True)
    (registry / "data.csv").write_bytes(content)
    (registry / "metadata.json").write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "sha256": digest,
                "row_count": len(source),
                "date_range": {
                    "start": source["date"].min(),
                    "end": source["date"].max(),
                },
                "data_frequency": "daily",
                "is_synthetic": True,
                "data_source": "uploaded",
            }
        ),
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment["MEDIPREDICT_UPLOADS_PATH"] = str(tmp_path / "uploads")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ml.build_dataset",
            dataset_id,
            "--horizon",
            "1",
            "--minimum-records-per-facility-item",
            "1",
            "--minimum-facility-items",
            "1",
            "--minimum-positives",
            "1",
            "--output-root",
            str(tmp_path / "features"),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    output_dir = Path(completed.stdout.split("Feature dataset saved: ", 1)[1].strip())
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    feature_table = pd.read_csv(output_dir / "features.csv")
    report = (output_dir / "report.md").read_text(encoding="utf-8")

    assert metadata["is_synthetic"] is True
    assert metadata["dataset_hash"] == digest
    assert metadata["frequency"] == "daily"
    assert metadata["horizon"] == 1
    assert metadata["label_mode"] == "new_stockout"
    assert len(feature_table) == len(source)
    assert set(feature_table["is_synthetic"].astype(str).str.casefold()) == {"true"}
    assert report.startswith("# SYNTHETIC - not evidence of real-world performance")
    assert metadata["label_prevalence"]["overall"]["rows"] > 0
    assert metadata["label_prevalence"]["facility_type"]
    assert metadata["label_prevalence"]["district"]
    assert metadata["label_prevalence"]["item_id"]
    assert metadata["feature_availability"]["rainfall_anomaly"]["available_rows"] == 0
