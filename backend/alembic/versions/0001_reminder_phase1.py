"""Add tenant consent and complete agency reminder settings/log fields.

Revision ID: 0001_reminder_phase1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import MetaData, Table, inspect, text, update

from app import models
from app.database import Base
from app.phone_numbers import normalize_sa_phone

revision = "0001_reminder_phase1"
down_revision = None
branch_labels = None
depends_on = None


def _columns(connection, table_name):
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def upgrade() -> None:
    connection = op.get_bind()
    # The app historically bootstrapped tables with metadata.create_all(). Keep
    # fresh databases compatible while applying additive changes to old ones.
    Base.metadata.create_all(connection)

    user_columns = _columns(connection, "users")
    additions = [
        ("whatsapp_opt_in", sa.Boolean(), "BOOLEAN NOT NULL DEFAULT 0"),
        ("sms_opt_in", sa.Boolean(), "BOOLEAN NOT NULL DEFAULT 0"),
        ("email_opt_in", sa.Boolean(), "BOOLEAN NOT NULL DEFAULT 0"),
        ("consent_recorded_at", sa.DateTime(), None),
        ("consent_recorded_by", sa.Integer(), None),
    ]
    for name, column_type, sqlite_definition in additions:
        if name not in user_columns:
            if sqlite_definition and connection.dialect.name == "sqlite":
                op.add_column("users", sa.Column(name, column_type, nullable=False,
                                                   server_default=sa.text("0")))
            elif name == "consent_recorded_by":
                if connection.dialect.name == "sqlite":
                    with op.batch_alter_table("users", recreate="always") as batch:
                        batch.add_column(sa.Column(name, column_type,
                                                   sa.ForeignKey("users.id"), nullable=True))
                else:
                    op.add_column("users", sa.Column(name, column_type,
                                                       sa.ForeignKey("users.id"), nullable=True))
            else:
                op.add_column("users", sa.Column(name, column_type, nullable=name not in {
                    "whatsapp_opt_in", "sms_opt_in", "email_opt_in"
                }, server_default=sa.text("false") if name in {
                    "whatsapp_opt_in", "sms_opt_in", "email_opt_in"
                } else None))

    settings_columns = _columns(connection, "agency_reminder_settings")
    if "reminders_enabled" not in settings_columns:
        op.add_column("agency_reminder_settings", sa.Column(
            "reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    if "enabled_channels" not in settings_columns:
        op.add_column("agency_reminder_settings", sa.Column(
            "enabled_channels", sa.JSON(), nullable=True))
        settings = Table("agency_reminder_settings", MetaData(), autoload_with=connection)
        connection.execute(update(settings).values(
            enabled_channels=["whatsapp", "sms", "email"]
        ))

    log_columns = _columns(connection, "agency_rent_reminder_logs")
    if "skip_reason" not in log_columns:
        op.add_column("agency_rent_reminder_logs", sa.Column("skip_reason", sa.String(200)))
    if "delivered_at" not in log_columns:
        op.add_column("agency_rent_reminder_logs", sa.Column("delivered_at", sa.DateTime()))

    # Preserve existing opt-ins and their audit time from the legacy preference
    # table; it did not capture who recorded consent, so that field stays null.
    if "tenant_channel_preferences" in inspect(connection).get_table_names():
        connection.execute(text("""
            UPDATE users SET
                whatsapp_opt_in = COALESCE((SELECT whatsapp_opt_in FROM tenant_channel_preferences p
                                            WHERE p.tenant_id = users.id), whatsapp_opt_in),
                sms_opt_in = COALESCE((SELECT sms_opt_in FROM tenant_channel_preferences p
                                       WHERE p.tenant_id = users.id), sms_opt_in),
                email_opt_in = COALESCE((SELECT email_opt_in FROM tenant_channel_preferences p
                                         WHERE p.tenant_id = users.id), email_opt_in),
                consent_recorded_at = COALESCE((SELECT updated_at FROM tenant_channel_preferences p
                                                WHERE p.tenant_id = users.id), consent_recorded_at)
            WHERE role = 'tenant'
        """))

    # Normalize legacy numbers that parse cleanly. Keep invalid legacy values
    # intact for landlord review instead of silently deleting contact data.
    rows = connection.execute(text("SELECT id, phone FROM users WHERE role = 'tenant' AND phone IS NOT NULL"))
    for user_id, phone in rows:
        try:
            normalized = normalize_sa_phone(phone)
        except ValueError:
            continue
        connection.execute(text("UPDATE users SET phone = :phone WHERE id = :id"),
                           {"phone": normalized, "id": user_id})


def downgrade() -> None:
    # Consent/settings/log data is retained; dropping it would lose user data.
    # This migration is intentionally forward-only.
    pass
