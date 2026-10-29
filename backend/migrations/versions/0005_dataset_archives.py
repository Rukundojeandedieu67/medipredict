"""Track immutable reference dataset archives stored in object storage.

Revision ID: 0005_dataset_archives
Revises: 0004_dataset_and_model_registry
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_dataset_archives"
down_revision = "0004_dataset_and_model_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_archives",
        sa.Column("archive_id", sa.String(length=80), primary_key=True),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.String(length=20), nullable=False),
        sa.Column("period_end", sa.String(length=20), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_dataset_archives_sha256", "dataset_archives", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_dataset_archives_sha256", table_name="dataset_archives")
    op.drop_table("dataset_archives")
