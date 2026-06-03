from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

# We are using SQLite for easy local testing
SQLALCHEMY_DATABASE_URL = "sqlite:///./app.db"

# connect_args={"check_same_thread": False} is needed only for SQLite
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# This line creates the tables in the database based on models.py
Base.metadata.create_all(bind=engine)

# The dependency function that main.py needs
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()