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
        provenance_table = sa.table(
            table,
            sa.column("is_synthetic", sa.Boolean()),
            sa.column("data_source", sa.String(length=32)),
        )
        op.execute(
            sa.update(provenance_table)
            .where(
                sa.or_(
                    provenance_table.c.is_synthetic.is_(None),
                    provenance_table.c.data_source.is_(None),
                )
            )
            .values(is_synthetic=True, data_source="synthetic")
        )


def downgrade() -> None:
    for table in ("predictions", "daily_stock_logs"):
        op.drop_column(table, "data_source")
        op.drop_column(table, "is_synthetic")
