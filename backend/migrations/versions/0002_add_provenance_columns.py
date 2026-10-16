"""Add provenance fields to stock logs and predictions.

Revision ID: 0002_add_provenance
Revises: 0001_baseline
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_provenance"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("daily_stock_logs", "predictions"):
        op.add_column(table, sa.Column("is_synthetic", sa.Boolean(), nullable=True))
        op.add_column(table, sa.Column("data_source", sa.String(length=32), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {table} "
                "SET is_synthetic = 1, data_source = 'synthetic' "
                "WHERE is_synthetic IS NULL OR data_source IS NULL"
            )
        )


def downgrade() -> None:
    for table in ("predictions", "daily_stock_logs"):
        op.drop_column(table, "data_source")
        op.drop_column(table, "is_synthetic")
