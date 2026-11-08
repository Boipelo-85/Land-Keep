"""Add landlord Paystack payment controls without altering existing ledgers."""
from alembic import op
import sqlalchemy as sa
from app.models import PaystackSettings
revision = "0011_paystack"
down_revision = "0010_unique_rent_period"
branch_labels = None
depends_on = None


def upgrade():
    PaystackSettings.__table__.create(op.get_bind(), checkfirst=True)
    if "checkout_url" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("payment_attempts")}:
        op.add_column("payment_attempts", sa.Column("checkout_url", sa.Text(), nullable=True))
    if "uq_paystack_open_charge" not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("payment_attempts")}:
        op.create_index("uq_paystack_open_charge", "payment_attempts", ["rent_record_id"], unique=True,
            sqlite_where=sa.text("provider = 'paystack' AND status IN ('initiated', 'pending')"),
            postgresql_where=sa.text("provider = 'paystack' AND status IN ('initiated', 'pending')"))


def downgrade():
    op.drop_index("uq_paystack_open_charge", table_name="payment_attempts")
    PaystackSettings.__table__.drop(op.get_bind(), checkfirst=True)
    if "checkout_url" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("payment_attempts")}:
        op.drop_column("payment_attempts", "checkout_url")
