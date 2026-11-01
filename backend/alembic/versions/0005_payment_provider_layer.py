"""Introduce provider-neutral payments and integer-cent payment ledger.

Revision ID: 0005_payment_provider_layer
Revises: 0004_landlord_payment_routing
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "0005_payment_provider_layer"
down_revision = "0004_landlord_payment_routing"
branch_labels = None
depends_on = None


def _cols(connection, table):
    return {column["name"] for column in inspect(connection).get_columns(table)}


def _add_missing(connection, table, columns):
    existing = _cols(connection, table)
    for name, column in columns:
        if name not in existing:
            op.add_column(table, column)
            existing.add(name)


def upgrade() -> None:
    connection = op.get_bind()

    # Preserve the old Rand values, rounded once to cents, before dropping the
    # floating-point payment columns. RentCharge/Lease pricing remains in its
    # established Rand representation; the payment ledger itself is integer cents.
    payment_columns = _cols(connection, "payments")
    if "amount_cents" not in payment_columns:
        op.add_column("payments", sa.Column("amount_cents", sa.Integer(), nullable=True))
        if "amount" in payment_columns:
            connection.execute(text(
                "UPDATE payments SET amount_cents = CAST(ROUND(amount * 100) AS INTEGER)"
            ))
        else:
            connection.execute(text("UPDATE payments SET amount_cents = 0 WHERE amount_cents IS NULL"))
        payment_columns = _cols(connection, "payments")
    payment_additions = [
        ("provider", sa.Column("provider", sa.String(20), nullable=False, server_default="manual")),
        ("reference", sa.Column("reference", sa.String(100), nullable=True)),
        ("provider_payment_id", sa.Column("provider_payment_id", sa.String(100), nullable=True)),
    ]
    _add_missing(connection, "payments", payment_additions)
    if "amount" in _cols(connection, "payments"):
        with op.batch_alter_table("payments", recreate="always" if connection.dialect.name == "sqlite" else "auto") as batch:
            batch.alter_column("amount_cents", existing_type=sa.Integer(), nullable=False)
            batch.drop_column("amount")
    if "ix_payments_provider_payment_id" not in {i["name"] for i in inspect(connection).get_indexes("payments")}:
        op.create_index("ix_payments_provider_payment_id", "payments", ["provider_payment_id"])

    attempt_columns = _cols(connection, "payment_attempts")
    new_attempt_columns = [
        ("agency_id", sa.Column("agency_id", sa.Integer(), nullable=True)),
        ("lease_id", sa.Column("lease_id", sa.Integer(), nullable=True)),
        ("rent_record_id", sa.Column("rent_record_id", sa.Integer(), nullable=True)),
        ("amount_cents", sa.Column("amount_cents", sa.Integer(), nullable=True)),
        ("platform_fee_cents", sa.Column("platform_fee_cents", sa.Integer(), nullable=False, server_default="0")),
        ("currency", sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR")),
        ("provider", sa.Column("provider", sa.String(20), nullable=False, server_default="payfast")),
        ("our_reference", sa.Column("our_reference", sa.String(80), nullable=True)),
        ("provider_payment_id", sa.Column("provider_payment_id", sa.String(100), nullable=True)),
        ("failure_reason", sa.Column("failure_reason", sa.Text(), nullable=True)),
        ("payment_method", sa.Column("payment_method", sa.String(40), nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime(), nullable=True)),
        ("completed_at", sa.Column("completed_at", sa.DateTime(), nullable=True)),
    ]
    _add_missing(connection, "payment_attempts", new_attempt_columns)
    attempt_columns = _cols(connection, "payment_attempts")
    # SQLite cannot add foreign keys with ALTER TABLE; batch mode rebuilds the
    # table and keeps this migration portable to the project's default DB.
    current_fks = inspect(connection).get_foreign_keys("payment_attempts")
    fk_columns = {tuple(fk.get("constrained_columns", [])) for fk in current_fks}
    missing_fks = [
        ("agency_id", "users"), ("lease_id", "leases"),
        ("rent_record_id", "rent_charges"),
    ]
    if any((column,) not in fk_columns for column, _ in missing_fks):
        with op.batch_alter_table("payment_attempts") as batch:
            for column, target in missing_fks:
                if (column,) not in fk_columns:
                    batch.create_foreign_key(f"fk_payment_attempts_{column}", target, [column], ["id"])

    # Upgrade records created by the earlier prototype checkout, when present.
    if "charge_id" in attempt_columns:
        if "amount" in attempt_columns:
            connection.execute(text(
                "UPDATE payment_attempts SET amount_cents = CAST(ROUND(amount * 100) AS INTEGER) "
                "WHERE amount_cents IS NULL"
            ))
        connection.execute(text("""
            UPDATE payment_attempts SET
                rent_record_id = charge_id,
                lease_id = (SELECT lease_id FROM rent_charges WHERE id = charge_id),
                agency_id = (SELECT p.landlord_id FROM properties p
                             JOIN units u ON u.property_id = p.id
                             JOIN leases l ON l.unit_id = u.id
                             JOIN rent_charges rc ON rc.lease_id = l.id
                             WHERE rc.id = charge_id),
                our_reference = COALESCE(our_reference, payment_reference),
                provider_payment_id = COALESCE(provider_payment_id, provider_transaction_id),
                status = CASE status WHEN 'paid' THEN 'succeeded' ELSE status END,
                completed_at = COALESCE(completed_at, paid_at),
                updated_at = COALESCE(updated_at, paid_at, created_at)
        """))
    if "amount_cents" in _cols(connection, "payment_attempts"):
        connection.execute(text("UPDATE payment_attempts SET amount_cents = 0 WHERE amount_cents IS NULL"))
        connection.execute(text("UPDATE payment_attempts SET our_reference = 'legacy-' || id WHERE our_reference IS NULL"))
        connection.execute(text("UPDATE payment_attempts SET updated_at = created_at WHERE updated_at IS NULL"))
        invalid = connection.execute(text("""
            SELECT COUNT(*) FROM payment_attempts
            WHERE agency_id IS NULL OR lease_id IS NULL OR rent_record_id IS NULL
        """)).scalar_one()
        if invalid:
            raise RuntimeError(
                f"Cannot migrate {invalid} payment attempt(s): lease, rent charge, or agency "
                "ownership could not be determined. Resolve those records before retrying."
            )

    # Retain old reference/foreign-key columns for compatibility with records
    # already audited by the earlier app, but remove the old float amount.
    if "amount" in _cols(connection, "payment_attempts"):
        with op.batch_alter_table("payment_attempts", recreate="always" if connection.dialect.name == "sqlite" else "auto") as batch:
            batch.alter_column("agency_id", existing_type=sa.Integer(), nullable=False)
            batch.alter_column("lease_id", existing_type=sa.Integer(), nullable=False)
            batch.alter_column("rent_record_id", existing_type=sa.Integer(), nullable=False)
            batch.alter_column("amount_cents", existing_type=sa.Integer(), nullable=False)
            batch.alter_column("our_reference", existing_type=sa.String(80), nullable=False)
            batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)
            batch.drop_column("amount")
    for index_name, table, column in (
        ("ix_payment_attempts_agency_id", "payment_attempts", "agency_id"),
        ("ix_payment_attempts_lease_id", "payment_attempts", "lease_id"),
        ("ix_payment_attempts_rent_record_id", "payment_attempts", "rent_record_id"),
        ("ix_payment_attempts_provider_payment_id", "payment_attempts", "provider_payment_id"),
    ):
        if index_name not in {i["name"] for i in inspect(connection).get_indexes(table)}:
            op.create_index(index_name, table, [column])
    attempt_unique = {c.get("name") for c in inspect(connection).get_unique_constraints("payment_attempts")}
    if "uq_payment_attempt_our_reference" not in attempt_unique:
        with op.batch_alter_table("payment_attempts") as batch:
            batch.create_unique_constraint("uq_payment_attempt_our_reference", ["our_reference"])
    if "uq_payment_attempt_provider_payment_id" not in attempt_unique:
        with op.batch_alter_table("payment_attempts") as batch:
            batch.create_unique_constraint("uq_payment_attempt_provider_payment_id", ["provider_payment_id"])

    tables = set(inspect(connection).get_table_names())
    if "payment_notification_logs" not in tables:
        op.create_table(
            "payment_notification_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("provider_payment_id", sa.String(100), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ip_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("server_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("failure_reason", sa.String(300), nullable=True),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("provider", "provider_payment_id", "status",
                                name="uq_payment_notification_provider_payment_status"),
        )
        op.create_index("ix_payment_notification_logs_provider", "payment_notification_logs", ["provider"])

    tables = set(inspect(connection).get_table_names())
    if "agency_payment_settings" not in tables:
        op.create_table(
            "agency_payment_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("agency_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("payments_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("payfast_merchant_id", sa.String(8), nullable=True),
            sa.Column("who_pays_fees", sa.String(10), nullable=False, server_default="landlord"),
            sa.Column("platform_fee_type", sa.String(12), nullable=False, server_default="fixed"),
            sa.Column("platform_fee_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("platform_fee_basis_points", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("allow_partial_payments", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("minimum_partial_amount_cents", sa.Integer(), nullable=False, server_default="500"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("agency_id", name="uq_agency_payment_settings_agency_id"),
        )
        op.create_index("ix_agency_payment_settings_agency_id", "agency_payment_settings", ["agency_id"])
        if "landlord_payment_settings" in tables:
            connection.execute(text("""
                INSERT INTO agency_payment_settings
                    (agency_id, payments_enabled, payfast_merchant_id, who_pays_fees,
                     platform_fee_type, platform_fee_cents, platform_fee_basis_points,
                     allow_partial_payments, minimum_partial_amount_cents, updated_at)
                SELECT landlord_id, 0, payfast_merchant_id, 'landlord', 'fixed', 0, 0, 0, 500,
                       COALESCE(updated_at, CURRENT_TIMESTAMP)
                FROM landlord_payment_settings
                WHERE landlord_id NOT IN (SELECT agency_id FROM agency_payment_settings)
            """))


def downgrade() -> None:
    # Payment cents and provider audit data are financial records; keep them.
    pass
