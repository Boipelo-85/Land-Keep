"""Add the scoped automation message log and simulated phone history."""
from alembic import op
from app.models import AutomationMessage

revision = "0012_automation_messages"
down_revision = "0011_paystack"
branch_labels = None
depends_on = None


def upgrade():
    AutomationMessage.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    AutomationMessage.__table__.drop(op.get_bind())
