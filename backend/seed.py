from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Unit, User
from app.security import hash_password


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        landlord = db.scalar(select(User).where(User.email == "landlord@example.com"))
        if landlord is None:
            landlord = User(
                email="landlord@example.com",
                full_name="Demo Landlord",
                password_hash=hash_password("LandKeep123!"),
                role="landlord",
                id_number="8001015009087",
            )
            db.add(landlord)
            db.flush()
            db.add_all([
                Unit(
                    landlord_id=landlord.id,
                    title="Sunny 2-bedroom apartment",
                    address="12 Main Road, Johannesburg",
                    monthly_rent=8500,
                    bedrooms=2,
                ),
                Unit(
                    landlord_id=landlord.id,
                    title="Garden cottage",
                    address="8 Oak Avenue, Pretoria",
                    monthly_rent=6200,
                    bedrooms=1,
                ),
            ])
        tenant = db.scalar(select(User).where(User.email == "tenant@example.com"))
        if tenant is None:
            tenant = User(
                email="tenant@example.com",
                full_name="Demo Tenant",
                password_hash=hash_password("LandKeep123!"),
                role="tenant",
                id_number="9001015009086",
            )
            db.add(tenant)
        db.commit()
    print("Seed complete. Demo landlord and tenant accounts are ready.")


if __name__ == "__main__":
    seed()
