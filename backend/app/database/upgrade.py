"""Idempotent local SQLite upgrades. create_all does not add columns to existing tables."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def apply_schema_upgrades(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("messages")}
    with engine.begin() as connection:
        if "direction" not in columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN direction VARCHAR(16)"))
        if "direction_source" not in columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN direction_source VARCHAR(16)"))
        connection.execute(
            text(
                """
                UPDATE messages
                SET direction = CASE WHEN is_outgoing = 1 THEN 'outgoing' ELSE 'incoming' END
                WHERE direction IS NULL OR direction = ''
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE messages
                SET direction_source = CASE
                    WHEN direction = 'unknown' THEN 'unknown'
                    ELSE 'native'
                END
                WHERE direction_source IS NULL OR direction_source = ''
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE messages
                SET is_outgoing = CASE WHEN direction = 'outgoing' THEN 1 ELSE 0 END
                WHERE direction IS NOT NULL AND direction != ''
                """
            )
        )
