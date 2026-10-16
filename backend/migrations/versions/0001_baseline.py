"""Baseline for the existing MediPredict SQLAlchemy schema.

Revision ID: 0001_baseline
Revises: None
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "facilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("facility_type", sa.String(length=80), nullable=False),
        sa.Column("district", sa.String(length=100), nullable=False),
        sa.Column("province", sa.String(length=100), nullable=False),
        sa.Column("under5_population", sa.Integer(), nullable=False),
        sa.Column("poverty_rate", sa.Float(), nullable=False),
        sa.Column("malaria_prevalence", sa.Float(), nullable=False),
    )
    op.create_index("ix_facilities_name", "facilities", ["name"], unique=True)
    op.create_index("ix_facilities_district", "facilities", ["district"], unique=False)

    op.create_table(
        "medicines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("safety_days", sa.Integer(), nullable=False),
    )
    op.create_index("ix_medicines_code", "medicines", ["code"], unique=True)

    op.create_table(
        "daily_stock_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), nullable=False),
        sa.Column("medicine_id", sa.Integer(), nullable=False),
        sa.Column("reporting_date", sa.String(length=20), nullable=False),
        sa.Column("stock_units", sa.Float(), nullable=False),
        sa.Column("daily_consumption", sa.Float(), nullable=False),
        sa.Column("rainy_season", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["facility_id"], ["facilities.id"]),
        sa.ForeignKeyConstraint(["medicine_id"], ["medicines.id"]),
        sa.UniqueConstraint("facility_id", "medicine_id", "reporting_date"),
    )
    op.create_index("ix_daily_stock_logs_facility_id", "daily_stock_logs", ["facility_id"], unique=False)
    op.create_index("ix_daily_stock_logs_medicine_id", "daily_stock_logs", ["medicine_id"], unique=False)
    op.create_index("ix_daily_stock_logs_reporting_date", "daily_stock_logs", ["reporting_date"], unique=False)

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), nullable=False),
        sa.Column("medicine_id", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("lead_time_days", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["facility_id"], ["facilities.id"]),
        sa.ForeignKeyConstraint(["medicine_id"], ["medicines.id"]),
    )
    op.create_index("ix_predictions_facility_id", "predictions", ["facility_id"], unique=False)
    op.create_index("ix_predictions_medicine_id", "predictions", ["medicine_id"], unique=False)
    op.create_index("ix_predictions_risk_level", "predictions", ["risk_level"], unique=False)


def downgrade() -> None:
    raise RuntimeError(
        "The baseline migration is intentionally non-destructive. "
        "Do not downgrade past the baseline or drop application tables."
    )
