"""Add advisory priority score and agency-scoped contractor work orders."""
from alembic import op
import sqlalchemy as sa
from app.database import Base
from app import models  # noqa: F401
revision = '0009_priority_contractors'
down_revision = '0008_unit_number_unique'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    Base.metadata.create_all(connection)
    columns = {c['name'] for c in sa.inspect(connection).get_columns('maintenance_requests')}
    if 'classification_priority_score' not in columns:
        op.add_column('maintenance_requests', sa.Column('classification_priority_score', sa.Float(), nullable=True))


def downgrade():
    pass
