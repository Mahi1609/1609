# discovery/db.py
"""
DB initialization helper. Uses SQLModel / SQLAlchemy.
Switch DB by setting env var DATABASE_URL, e.g.:
  export DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/newsdb
If DATABASE_URL is missing, defaults to sqlite:///./data/news.db
"""

import os
from sqlmodel import SQLModel, create_engine
from sqlmodel import Session
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", None)
if not DATABASE_URL:
    # default fallback (local sqlite file in repo/data/)
    here = os.path.dirname(os.path.dirname(__file__))  # discovery/..
    default_path = os.path.join(here, "data", "news.db")
    os.makedirs(os.path.dirname(default_path), exist_ok=True)
    DATABASE_URL = f"sqlite:///{default_path}"

# Create SQLAlchemy engine (synchronous). Use echo=True temporarily if debugging.
_engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})

def get_engine():
    return _engine

@contextmanager
def get_session():
    """
    Return a context-managed SQLModel session compatible across processes.
    Usage:
        with get_session() as session:
            session.exec(...)
    """
    with Session(_engine) as s:
        yield s

def init_db():
    """
    Create tables if they don't exist. Call this at process startup (FastAPI & Celery worker).
    """
    SQLModel.metadata.create_all(_engine)
