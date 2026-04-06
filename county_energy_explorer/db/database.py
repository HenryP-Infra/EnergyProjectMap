"""
Database engine, session factory, and table initialisation.
Supports SQLite (dev) and PostgreSQL (prod) transparently.
The GIN full-text index is created only when connected to PostgreSQL.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, Session

from config import settings
from db.models import Base

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=False,
    pool_pre_ping=True,
)

# Enable WAL mode for SQLite for better concurrent read performance
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they do not exist, then apply any PG-specific DDL."""
    Base.metadata.create_all(bind=engine)

    is_postgres = settings.database_url.startswith("postgresql")
    if is_postgres:
        _apply_postgres_extras()

    log.info("Database initialised: %s", settings.database_url.split("@")[-1])


def _apply_postgres_extras() -> None:
    """
    Apply PostgreSQL-specific DDL that cannot be expressed in SQLAlchemy column
    definitions portably:
      1. GENERATED ALWAYS AS tsvector column for full-text search.
      2. GIN index on that column.
    These statements are idempotent (IF NOT EXISTS / DO NOTHING).
    """
    with engine.begin() as conn:
        # Add generated tsvector column if absent
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='documents' AND column_name='raw_text_tsv'
                ) THEN
                    ALTER TABLE documents
                        ADD COLUMN raw_text_tsv tsvector
                        GENERATED ALWAYS AS (
                            to_tsvector('english', coalesce(raw_text, ''))
                        ) STORED;
                END IF;
            END $$;
        """))

        # Create GIN index if absent
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_documents_raw_text_gin
                ON documents USING GIN (raw_text_tsv);
        """))

    log.info("PostgreSQL GIN full-text index applied.")


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

@contextmanager
def get_db() -> Session:
    """Context manager that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    """Return a raw session — caller is responsible for close/commit."""
    return SessionLocal()
