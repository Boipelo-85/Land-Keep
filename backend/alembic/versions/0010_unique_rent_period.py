"""Enforce one rent charge per lease and billing month without deleting records."""
from alembic import op
import sqlalchemy as sa

revision = "0010_unique_rent_period"
down_revision = "0009_priority_contractors"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicates = connection.execute(sa.text(
        "SELECT lease_id, period FROM rent_charges GROUP BY lease_id, period HAVING COUNT(*) > 1"
    )).first()
    if duplicates:
        raise RuntimeError("Duplicate rent charges exist. Review billing records before applying this migration; no records were deleted.")
    inspector = sa.inspect(connection)
    names = {item["name"] for item in inspector.get_unique_constraints("rent_charges")}
    names.update(item["name"] for item in inspector.get_indexes("rent_charges"))
    if "uq_rent_charge_lease_period" not in names:
        op.create_index("uq_rent_charge_lease_period", "rent_charges", ["lease_id", "period"], unique=True)


def downgrade():
    indexes = sa.inspect(op.get_bind()).get_indexes("rent_charges")
    if any(item["name"] == "uq_rent_charge_lease_period" for item in indexes):
        op.drop_index("uq_rent_charge_lease_period", table_name="rent_charges")
