"""
Database configuration and session management.
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import os
from pathlib import Path
from dotenv import load_dotenv

# Always load .env from the project root, regardless of current working directory
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Database URL from environment.
# Default to MySQL DSN; override via DATABASE_URL env in production.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://user:password@localhost:3306/ai_study_assistant",
)

# Create engine
connect_args = {}
poolclass = None
if DATABASE_URL.startswith("sqlite"):
    # Only used for local/dev if you explicitly opt into SQLite
    connect_args = {"check_same_thread": False}
    if ":memory:" in DATABASE_URL:
        poolclass = StaticPool  # Share single in-memory DB across connections
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args=connect_args,
    poolclass=poolclass,
    echo=False,  # Set to True for SQL query logging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """
    FastAPI dependency that provides a SQLAlchemy session.

    - Opens a new session per request
    - Rolls back on error
    - Closes the session in all cases
    """
    db = SessionLocal()
    try:
        yield db
        # Commit is typically handled explicitly in route/CRUD code,
        # so we don't auto-commit here.
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session():
    """Return a new session for use in background tasks (caller must close)."""
    return SessionLocal()

