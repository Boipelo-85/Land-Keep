"""Track the currency of provider-reported messaging charges."""
import sqlalchemy as sa
from alembic import op

revision = "0015_actual_message_currency"
down_revision = "0014_lease_notifications"
branch_labels = None
depends_on = None


def upgrade():
    columns = sa.inspect(op.get_bind()).get_columns("automation_messages")
    if not any(column["name"] == "actual_cost_currency" for column in columns):
        op.add_column("automation_messages", sa.Column("actual_cost_currency", sa.String(3)))


def downgrade():
    with op.batch_alter_table("automation_messages") as batch:
        batch.drop_column("actual_cost_currency")
