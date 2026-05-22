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
    tables = set(inspector.get_table_names())
    if "orders" in tables:
        _add_columns_if_missing(
            engine,
            inspector,
            "orders",
            {
                "detection_route": "TEXT DEFAULT '[]'",
                "preprocessing_profile": "TEXT DEFAULT '{}'",
                "sample_storage_class": "VARCHAR(80)",
                "transfer_requirements": "TEXT DEFAULT '{}'",
                "parent_order_id": "VARCHAR(40)",
                "retest_reason": "TEXT",
            },
        )
    if "detection_projects" in tables:
        _add_columns_if_missing(
            engine,
            inspector,
            "detection_projects",
            {
                "lab_area": "VARCHAR(80) DEFAULT 'lab'",
                "setup_minutes": "INTEGER DEFAULT 0",
                "operator_requirements": "TEXT DEFAULT '{}'",
                "consumable_type": "VARCHAR(80)",
                "consumable_units_per_batch": "INTEGER DEFAULT 0",
            },
        )
    if "schedule_steps" in tables:
        _add_columns_if_missing(
            engine,
            inspector,
            "schedule_steps",
            {
                "step_kind": "VARCHAR(40)",
                "lab_area": "VARCHAR(80)",
                "assigned_employee_ids": "TEXT DEFAULT '[]'",
                "resource_ids": "TEXT DEFAULT '[]'",
                "constraint_detail": "TEXT DEFAULT '{}'",
                "setup_minutes": "INTEGER",
                "staff_role": "VARCHAR(80)",
                "consumable_type": "VARCHAR(80)",
                "consumable_units": "INTEGER",
                "execution_status": "VARCHAR(30)",
                "locked": "INTEGER DEFAULT 0",
                "actual_start_time": "DATETIME",
                "actual_end_time": "DATETIME",
                "execution_note": "TEXT",
            },
        )
    if "scheduling_events" in tables:
        _add_columns_if_missing(
            engine,
            inspector,
            "scheduling_events",
            {
                "source": "VARCHAR(80) DEFAULT 'api'",
                "error_message": "TEXT",
            },
        )


def _add_columns_if_missing(engine, inspector, table_name: str, columns: dict[str, str]) -> None:
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    missing = [(name, definition) for name, definition in columns.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for name, definition in missing:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"))


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
