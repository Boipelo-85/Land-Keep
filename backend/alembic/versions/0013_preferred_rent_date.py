"""Store the applicant's preferred rent payment date."""

import sqlalchemy as sa
from alembic import op

revision = "0013_preferred_rent_date"
down_revision = "0012_automation_messages"
branch_labels = None
depends_on = None


def upgrade():
    # Older bootstrap revisions use the current model when creating fresh tables.
    columns = sa.inspect(op.get_bind()).get_columns("tenant_applications")
    if not any(column["name"] == "preferred_rent_date" for column in columns):
        op.add_column("tenant_applications", sa.Column("preferred_rent_date", sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table("tenant_applications") as batch:
        batch.drop_column("preferred_rent_date")
