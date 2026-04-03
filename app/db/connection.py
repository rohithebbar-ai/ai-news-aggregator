"""
Neon Postgres connection management via SQLAlchemy.
Provides a singleton engine and a context-managed Session.
"""

import os
import threading
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from dotenv import load_dotenv

load_dotenv()

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_lock = threading.Lock()


def get_engine() -> Engine:
    """Return a singleton SQLAlchemy engine."""
    global _engine, _session_factory
    with _lock:
        if _engine is None:
            url = os.getenv("DATABASE_URL", "")
            if not url:
                raise RuntimeError("DATABASE_URL environment variable is not set")
            _engine = create_engine(url, pool_pre_ping=True)
            _session_factory = sessionmaker(_engine)
        return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for SQLAlchemy sessions. Commits on success, rolls back on error."""
    get_engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
