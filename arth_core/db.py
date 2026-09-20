"""SQLAlchemy engine/session management. The engine is created lazily so the
DATABASE_URL can be set (or overridden by tests) before first use."""
from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from . import config


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def configure_engine(url: str | None = None) -> Engine:
    """(Re)create the engine. Call with no argument to use DATABASE_URL."""
    global _engine, _SessionLocal
    url = url or config.database_url()
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _record):  # enforce FK cascades on SQLite too
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return engine


def get_engine() -> Engine:
    return _engine or configure_engine()


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def init_db() -> None:
    """Create any missing tables. Safe to call on every startup."""
    from . import models  # noqa: F401  (registers tables on Base.metadata)
    Base.metadata.create_all(get_engine())


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
