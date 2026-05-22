from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from db.session import create_tables, get_session_factory


def test_create_tables_adds_detection_route_to_existing_sqlite_orders_table(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE orders (
                    id VARCHAR(36) PRIMARY KEY,
                    order_type VARCHAR(30) NOT NULL,
                    sample_name VARCHAR(120) NOT NULL,
                    sample_quantity INTEGER NOT NULL,
                    certification_type VARCHAR(40) NOT NULL,
                    requested_projects TEXT DEFAULT '[]',
                    status VARCHAR(30) DEFAULT 'pending',
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )

    session_factory = get_session_factory(database_url)
    create_tables(session_factory)

    columns = {column["name"] for column in inspect(session_factory.kw["bind"]).get_columns("orders")}
    assert "detection_route" in columns
