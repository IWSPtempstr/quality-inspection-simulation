from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from db.models import Base


def _ensure_sqlite_parent(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    resolved_url = database_url or get_settings().database_url
    _ensure_sqlite_parent(resolved_url)
    engine = create_engine(
        resolved_url,
        connect_args={"check_same_thread": False} if resolved_url.startswith("sqlite") else {},
        future=True,
    )
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def create_tables(session_factory: sessionmaker[Session]) -> None:
    engine = session_factory.kw["bind"]
    Base.metadata.create_all(engine)
    _run_sqlite_migrations(engine)


def _run_sqlite_migrations(engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return
    inspector = inspect(engine)
    if "orders" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("orders")}
    if "detection_route" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE orders ADD COLUMN detection_route TEXT DEFAULT '[]'"))


def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
