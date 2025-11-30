from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

# Use DATABASE_URL from .env, e.g. postgresql://kartquake:kartquake@localhost:5432/kartquake
DATABASE_URL = settings.DATABASE_URL

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

engine = create_engine(
    DATABASE_URL,
    future=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

def get_db() -> Session:
    """
    FastAPI dependency that provides a database session and
    closes it after the request is done.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
