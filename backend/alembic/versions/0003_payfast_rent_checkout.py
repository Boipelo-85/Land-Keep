"""Add tenant hosted-gateway checkout tracking.

Revision ID: 0003_payfast_rent_checkout
Revises: 0002_maintenance_chat_storage
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_payfast_rent_checkout"
down_revision = "0002_maintenance_chat_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "payment_attempts" not in inspector.get_table_names():
        op.create_table(
        "payment_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_reference", sa.String(80), nullable=False),
        sa.Column("charge_id", sa.Integer(), sa.ForeignKey("rent_charges.id"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recipient_merchant_id", sa.String(8), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("provider_transaction_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("payment_reference", name="uq_payment_attempt_reference"),
        sa.UniqueConstraint("provider_transaction_id", name="uq_payment_attempt_provider_id"),
        )
        op.create_index("ix_payment_attempts_charge_id", "payment_attempts", ["charge_id"])
        op.create_index("ix_payment_attempts_tenant_id", "payment_attempts", ["tenant_id"])
        op.create_index("ix_payment_attempts_status", "payment_attempts", ["status"])

    payment_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("payments")}
    if "gateway_attempt_id" not in payment_columns:
        with op.batch_alter_table("payments") as batch:
            batch.add_column(sa.Column("gateway_attempt_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_payments_gateway_attempt_id", "payment_attempts", ["gateway_attempt_id"], ["id"])
            batch.create_unique_constraint("uq_payments_gateway_attempt_id", ["gateway_attempt_id"])
    payment_indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("payments")}
    if "ix_payments_gateway_attempt_id" not in payment_indexes:
        op.create_index("ix_payments_gateway_attempt_id", "payments", ["gateway_attempt_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_gateway_attempt_id", table_name="payments")
    with op.batch_alter_table("payments") as batch:
        batch.drop_constraint("uq_payments_gateway_attempt_id", type_="unique")
        batch.drop_constraint("fk_payments_gateway_attempt_id", type_="foreignkey")
        batch.drop_column("gateway_attempt_id")
    op.drop_index("ix_payment_attempts_status", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_tenant_id", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_charge_id", table_name="payment_attempts")
    op.drop_table("payment_attempts")
