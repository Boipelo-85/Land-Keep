"""Create synthetic demo data only in an empty database; never reset existing users."""
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import select
from app.database import Base, SessionLocal, engine
from app.models import User
from seed import main

if __name__ == '__main__':
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        populated = db.scalar(select(User.id).limit(1)) is not None
    if populated:
        print('Existing users found. Keeping your data; demo initialization skipped.')
    else:
        main()
