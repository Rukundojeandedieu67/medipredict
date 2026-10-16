import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def _config(database_path):
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.attributes["connection_url"] = f"sqlite:///{database_path.as_posix()}"
    return config


def test_provenance_migration_backfills_and_downgrades_without_losing_rows(tmp_path):
    baseline_database = tmp_path / "baseline.db"
    baseline_config = _config(baseline_database)

    command.upgrade(baseline_config, "0001_baseline")
    with sqlite3.connect(baseline_database) as connection:
        connection.execute(
            "INSERT INTO facilities "
            "(id, name, facility_type, district, province, under5_population, poverty_rate, malaria_prevalence) "
            "VALUES (1, 'F1', 'Health Center', 'D1', 'P1', 0, 0, 0)"
        )
        connection.execute(
            "INSERT INTO medicines (id, code, name, safety_days) VALUES (1, 'M1', 'Medicine 1', 14)"
        )
        connection.execute(
            "INSERT INTO daily_stock_logs "
            "(id, facility_id, medicine_id, reporting_date, stock_units, daily_consumption, rainy_season) "
            "VALUES (1, 1, 1, '2026-01-01', 20, 2, 0)"
        )
        connection.execute(
            "INSERT INTO predictions "
            "(id, facility_id, medicine_id, generated_at, lead_time_days, risk_level, confidence) "
            "VALUES (1, 1, 1, '2026-01-01 00:00:00', 10, 'MODERATE', 0)"
        )

    database_copy = tmp_path / "migration-copy.db"
    with sqlite3.connect(baseline_database) as source:
        with sqlite3.connect(database_copy) as destination:
            source.backup(destination)

    copy_config = _config(database_copy)
    command.upgrade(copy_config, "head")
    with sqlite3.connect(database_copy) as connection:
        for table in ("daily_stock_logs", "predictions"):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            provenance = connection.execute(
                f"SELECT is_synthetic, data_source FROM {table}"
            ).fetchall()
            assert count == 1
            assert provenance == [(1, "synthetic")]
            names = {
                column[1]
                for column in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            assert {"is_synthetic", "data_source"}.issubset(names)

    command.downgrade(copy_config, "0001_baseline")
    with sqlite3.connect(database_copy) as connection:
        for table in ("daily_stock_logs", "predictions"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
            names = {
                column[1]
                for column in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            assert "is_synthetic" not in names
            assert "data_source" not in names
