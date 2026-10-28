"""Add dataset registry, provenance events, and model release metadata.

Revision ID: 0004_dataset_and_model_registry
Revises: 0003_alert_notification_state
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_dataset_and_model_registry"
down_revision = "0003_alert_notification_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("dataset_id", sa.String(length=80), primary_key=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("storage_backend", sa.String(length=20), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("date_start", sa.String(length=20), nullable=True),
        sa.Column("date_end", sa.String(length=20), nullable=True),
        sa.Column("data_frequency", sa.String(length=12), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=True),
        sa.Column("data_source", sa.String(length=80), nullable=False),
        sa.Column("uploader", sa.String(length=160), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_datasets_sha256", "datasets", ["sha256"])

    op.create_table(
        "dataset_events",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(length=80),
            sa.ForeignKey("datasets.dataset_id"),
            nullable=False,
        ),
        sa.Column("dataset_sha256", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("actor_subject", sa.String(length=160), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_dataset_events_dataset_id", "dataset_events", ["dataset_id"])

    op.create_table(
        "model_releases",
        sa.Column("model_version", sa.String(length=80), primary_key=True),
        sa.Column(
            "source_dataset_id",
            sa.String(length=80),
            sa.ForeignKey("datasets.dataset_id"),
            nullable=True,
        ),
        sa.Column("source_dataset_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_key", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("model_sha256", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("model_validated", sa.Boolean(), nullable=False),
        sa.Column("release_status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_model_releases_source_dataset_id",
        "model_releases",
        ["source_dataset_id"],
    )
    op.create_index(
        "ix_model_releases_release_status",
        "model_releases",
        ["release_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_releases_release_status", table_name="model_releases")
    op.drop_index("ix_model_releases_source_dataset_id", table_name="model_releases")
    op.drop_table("model_releases")
    op.drop_index("ix_dataset_events_dataset_id", table_name="dataset_events")
    op.drop_table("dataset_events")
    op.drop_index("ix_datasets_sha256", table_name="datasets")
    op.drop_table("datasets")
