"""Prevent duplicate unit numbers within one property, including concurrent listings."""
from alembic import op
import sqlalchemy as sa

revision = '0008_unit_number_unique'
down_revision = '0007_maintenance_classifier'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Both SQLite and PostgreSQL use functional indexes; raw catalog lookup avoids
    # SQLAlchemy reflection skipping SQLite expression indexes.
    if connection.dialect.name == 'sqlite':
        exists = connection.scalar(sa.text("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='uq_unit_property_number'"))
    else:
        exists = connection.scalar(sa.text("SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema() AND indexname='uq_unit_property_number'"))
    if not exists:
        op.create_index('uq_unit_property_number', 'units', ['property_id', sa.text('lower(unit_number)')], unique=True)


def downgrade():
    op.drop_index('uq_unit_property_number', table_name='units')
