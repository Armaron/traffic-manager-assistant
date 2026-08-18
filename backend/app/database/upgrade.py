"""Idempotent local SQLite upgrades. create_all does not add columns to existing tables."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def apply_schema_upgrades(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    _upgrade_messages(engine)
    _upgrade_ai_analyses(engine)
    _upgrade_message_indexes(engine)


def _upgrade_ai_analyses(engine: Engine) -> None:
    inspector = inspect(engine)
    if "ai_analyses" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("ai_analyses")}
    with engine.begin() as connection:
        if "conversation_explanation_ru" not in columns:
            connection.execute(
                text("ALTER TABLE ai_analyses ADD COLUMN conversation_explanation_ru TEXT")
            )
        if "next_action_ru" not in columns:
            connection.execute(text("ALTER TABLE ai_analyses ADD COLUMN next_action_ru TEXT"))


def _upgrade_messages(engine: Engine) -> None:
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


def _upgrade_message_indexes(engine: Engine) -> None:
    inspector = inspect(engine)
    if "messages" not in inspector.get_table_names():
        return
    names = {index["name"] for index in inspector.get_indexes("messages")}
    if "ix_messages_chat_timestamp_id" in names:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_messages_chat_timestamp_id "
                "ON messages (chat_id, timestamp, id)"
            )
        )
