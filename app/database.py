# backend/database.py
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:///./ai_shopping_assistant2.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,  # set True if you want verbose SQL logs
)


def init_db() -> None:
    """
    Create all tables. Call this once on startup.
    """
    from . import models  # ensure models are imported so SQLModel sees them
    SQLModel.metadata.create_all(engine)


def get_session():
    """
    FastAPI dependency that yields a DB session.
    """
    with Session(engine) as session:
        yield session
