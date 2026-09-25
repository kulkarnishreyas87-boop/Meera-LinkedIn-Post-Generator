from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_settings().database_url
        _engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _):  # WAL lets the bot, API and scheduler share the file
            # Work around a well-known pysqlite pitfall: Python's built-in sqlite3 driver
            # manages transactions itself (issuing its own BEGIN/COMMIT under the hood) in a
            # way that conflicts with SQLAlchemy's own transaction tracking. Left alone, a
            # pooled connection can end up with no transaction ever properly (re)started for
            # a later read, so it keeps returning the WAL snapshot from whenever its last
            # transaction began - readers (like the API) can then serve stale data forever
            # after a write from a different connection (the bot, the scheduler), even though
            # the write is safely committed. See:
            # https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            dbapi_conn.isolation_level = None  # let SQLAlchemy drive transactions explicitly
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        @event.listens_for(_engine, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN")

    return _engine


def set_engine(engine) -> None:
    """Used by tests to swap in an in-memory database."""
    global _engine
    _engine = engine


def init_db() -> None:
    from app.db import models  # noqa: F401  (register tables)

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine) -> None:
    """Tiny forward-only migration: add nullable columns introduced after a DB was created."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing and col.nullable and not col.primary_key:
                    ddl = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session
