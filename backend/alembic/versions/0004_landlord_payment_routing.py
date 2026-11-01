"""Store each landlord's PayFast recipient merchant account.

Revision ID: 0004_landlord_payment_routing
Revises: 0003_payfast_rent_checkout
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_landlord_payment_routing"
down_revision = "0003_payfast_rent_checkout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "recipient_merchant_id" not in {
        column["name"] for column in inspector.get_columns("payment_attempts")
    }:
        with op.batch_alter_table("payment_attempts") as batch:
            batch.add_column(sa.Column("recipient_merchant_id", sa.String(8), nullable=False,
                                       server_default=""))

    if "landlord_payment_settings" not in inspector.get_table_names():
        op.create_table(
            "landlord_payment_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("landlord_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("payfast_merchant_id", sa.String(8), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("landlord_id", name="uq_landlord_payment_settings_landlord_id"),
        )
        op.create_index("ix_landlord_payment_settings_landlord_id", "landlord_payment_settings",
                        ["landlord_id"])


def downgrade() -> None:
    op.drop_index("ix_landlord_payment_settings_landlord_id", table_name="landlord_payment_settings")
    op.drop_table("landlord_payment_settings")
    with op.batch_alter_table("payment_attempts") as batch:
        batch.drop_column("recipient_merchant_id")
