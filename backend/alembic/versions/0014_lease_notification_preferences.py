"""Add lease notification preferences and reminder controls."""
import sqlalchemy as sa
from alembic import op

from app.models import ChannelCost, LeaseNotificationPreference, NotificationContactVerification

revision = "0014_lease_notifications"
down_revision = "0013_preferred_rent_date"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    LeaseNotificationPreference.__table__.create(connection, checkfirst=True)
    NotificationContactVerification.__table__.create(connection, checkfirst=True)
    ChannelCost.__table__.create(connection, checkfirst=True)
    for table, column in (
        ("agency_reminder_settings", sa.Column("lease_notification_policy", sa.JSON())),
        ("leases", sa.Column("reminders_paused", sa.Boolean())),
        ("automation_messages", sa.Column("billable", sa.Boolean())),
        ("automation_messages", sa.Column("cost_estimate", sa.Numeric(12, 4))),
        ("automation_messages", sa.Column("actual_cost", sa.Numeric(12, 4))),
        ("automation_messages", sa.Column("cost_currency", sa.String(3))),
    ):
        if column.name not in {item["name"] for item in sa.inspect(connection).get_columns(table)}:
            op.add_column(table, column)


def downgrade():
    ChannelCost.__table__.drop(op.get_bind())
    NotificationContactVerification.__table__.drop(op.get_bind())
    LeaseNotificationPreference.__table__.drop(op.get_bind())
    for table, name in (("agency_reminder_settings", "lease_notification_policy"), ("leases", "reminders_paused")):
        with op.batch_alter_table(table) as batch:
            batch.drop_column(name)
    with op.batch_alter_table("automation_messages") as batch:
        for name in ("billable", "cost_estimate", "actual_cost", "cost_currency"):
            batch.drop_column(name)
