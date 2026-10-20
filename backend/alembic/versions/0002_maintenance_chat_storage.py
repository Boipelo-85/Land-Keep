"""Add maintenance chat records and AI metadata to maintenance requests.

Revision ID: 0002_maintenance_chat_storage
Revises: 0001_reminder_phase1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.database import Base
from app import models  # noqa: F401

revision = "0002_maintenance_chat_storage"
down_revision = "0001_reminder_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Creates the new conversation/message/attachment tables. Existing request
    # tables remain untouched by create_all and receive additive columns below.
    Base.metadata.create_all(connection)
    request_columns = {column["name"] for column in inspect(connection).get_columns(
        "maintenance_requests"
    )}
    additions = [
        sa.Column("source", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("ai_category", sa.String(30), nullable=True),
        sa.Column("ai_urgency", sa.String(20), nullable=True),
        sa.Column("ai_summary", sa.String(500), nullable=True),
        sa.Column("ai_likely_cause", sa.String(500), nullable=True),
        sa.Column("tried_self_help", sa.Text(), nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
    ]
    missing = [column for column in additions if column.name not in request_columns]
    if missing:
        if connection.dialect.name == "sqlite":
            with op.batch_alter_table("maintenance_requests", recreate="always") as batch:
                for column in missing:
                    if column.name == "conversation_id":
                        column = sa.Column("conversation_id", sa.Integer(),
                                           sa.ForeignKey("maintenance_conversations.id",
                                                         name="fk_maintenance_requests_conversation_id"),
                                           nullable=True)
                    batch.add_column(column)
                if "conversation_id" in {column.name for column in missing}:
                    batch.create_unique_constraint(
                        "uq_maintenance_requests_conversation_id", ["conversation_id"]
                    )
        else:
            for column in missing:
                if column.name == "conversation_id":
                    column = sa.Column("conversation_id", sa.Integer(),
                                       sa.ForeignKey("maintenance_conversations.id",
                                                     name="fk_maintenance_requests_conversation_id"),
                                       nullable=True)
                op.add_column("maintenance_requests", column)
            if "conversation_id" in {column.name for column in missing}:
                op.create_index("uq_maintenance_requests_conversation_id",
                                "maintenance_requests", ["conversation_id"], unique=True)


def downgrade() -> None:
    # Keep conversation records and request metadata; they may contain user
    # reports or evidence. This migration is intentionally forward-only.
    pass
