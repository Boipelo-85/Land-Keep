"""Track merchant verification, settings changes, and small test checkouts.

Revision ID: 0006_payfast_merchant_verification
Revises: 0005_payment_provider_layer
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_payfast_merchant_verification"
down_revision = "0005_payment_provider_layer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    setting_columns = {column["name"] for column in inspect(connection).get_columns("agency_payment_settings")}
    missing_columns = [
        sa.Column("verification_status", sa.String(20), nullable=False,
                  server_default="not_verified"),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by_user_id", sa.Integer(), nullable=True),
    ]
    if any(column.name not in setting_columns for column in missing_columns):
        with op.batch_alter_table("agency_payment_settings") as batch:
            for column in missing_columns:
                if column.name not in setting_columns:
                    batch.add_column(column)
            current_fks = inspect(connection).get_foreign_keys("agency_payment_settings")
            if not any(fk.get("constrained_columns") == ["verified_by_user_id"] for fk in current_fks):
                batch.create_foreign_key("fk_agency_payment_settings_verified_by", "users",
                                         ["verified_by_user_id"], ["id"])

    tables = set(inspect(connection).get_table_names())
    if "agency_payment_settings_audit" not in tables:
        op.create_table(
            "agency_payment_settings_audit",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("agency_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("changed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("old_merchant_id_masked", sa.String(12), nullable=True),
            sa.Column("new_merchant_id_masked", sa.String(12), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    audit_indexes = {index["name"] for index in inspect(connection).get_indexes("agency_payment_settings_audit")}
    if "ix_agency_payment_settings_audit_agency_id" not in audit_indexes:
        op.create_index("ix_agency_payment_settings_audit_agency_id", "agency_payment_settings_audit", ["agency_id"])
    if "ix_agency_payment_settings_audit_created_at" not in audit_indexes:
        op.create_index("ix_agency_payment_settings_audit_created_at", "agency_payment_settings_audit", ["created_at"])

    if "merchant_verification_attempts" not in tables:
        op.create_table(
            "merchant_verification_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("agency_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("our_reference", sa.String(80), nullable=False, unique=True),
            sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="500"),
            sa.Column("status", sa.String(20), nullable=False, server_default="initiated"),
            sa.Column("provider_payment_id", sa.String(100), nullable=True, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
    verification_indexes = {index["name"] for index in inspect(connection).get_indexes("merchant_verification_attempts")}
    for index_name, column in (
        ("ix_merchant_verification_attempts_agency_id", "agency_id"),
        ("ix_merchant_verification_attempts_our_reference", "our_reference"),
        ("ix_merchant_verification_attempts_status", "status"),
    ):
        if index_name not in verification_indexes:
            op.create_index(index_name, "merchant_verification_attempts", [column],
                            unique=column == "our_reference")


def downgrade() -> None:
    op.drop_index("ix_merchant_verification_attempts_status", table_name="merchant_verification_attempts")
    op.drop_index("ix_merchant_verification_attempts_our_reference", table_name="merchant_verification_attempts")
    op.drop_index("ix_merchant_verification_attempts_agency_id", table_name="merchant_verification_attempts")
    op.drop_table("merchant_verification_attempts")
    op.drop_index("ix_agency_payment_settings_audit_created_at", table_name="agency_payment_settings_audit")
    op.drop_index("ix_agency_payment_settings_audit_agency_id", table_name="agency_payment_settings_audit")
    op.drop_table("agency_payment_settings_audit")
    with op.batch_alter_table("agency_payment_settings") as batch:
        batch.drop_constraint("fk_agency_payment_settings_verified_by", type_="foreignkey")
        batch.drop_column("verified_by_user_id")
        batch.drop_column("verified_at")
        batch.drop_column("verification_status")
