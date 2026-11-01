"""Record learned classifier model version and score without altering existing labels."""
from alembic import op
import sqlalchemy as sa

revision = '0007_maintenance_classifier'
down_revision = '0006_payfast_merchant_verification'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {c['name'] for c in sa.inspect(connection).get_columns('maintenance_requests')}
    for column in [sa.Column('classification_model_version', sa.String(80), nullable=True),
                   sa.Column('classification_score', sa.Float(), nullable=True)]:
        if column.name not in columns:
            op.add_column('maintenance_requests', column)


def downgrade():
    pass  # Keep recorded predictions and their provenance.
