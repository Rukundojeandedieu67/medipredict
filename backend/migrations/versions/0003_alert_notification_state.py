"""Persist per-alert email and SMS cooldown state.

Revision ID: 0003_alert_notification_state
Revises: 0002_add_provenance
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_alert_notification_state"
down_revision = "0002_add_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_notification_states",
        sa.Column("alert_key", sa.String(length=64), primary_key=True),
        sa.Column("email_severity", sa.String(length=20), nullable=True),
        sa.Column("email_sent_at", sa.DateTime(), nullable=True),
        sa.Column("sms_severity", sa.String(length=20), nullable=True),
        sa.Column("sms_sent_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("alert_notification_states")
