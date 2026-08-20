"""Isolate tests from data/traffic_manager.db before app modules load."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_TMP_DIR = tempfile.TemporaryDirectory(prefix="tma-pytest-")
_TEST_DB = Path(_TMP_DIR.name) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.resolve().as_posix()}"
os.environ["AI_PROVIDER"] = "mock"
os.environ["TYPEX_MODE"] = "mock"
os.environ["TELEGRAM_MODE"] = "mock"
os.environ["SLACK_MODE"] = "mock"
os.environ["SLACK_USER_TOKEN"] = ""
os.environ["SLACK_APP_TOKEN"] = ""
os.environ["SLACK_NOTIFICATION_CAPTURE_ENABLED"] = "false"
os.environ["SLACK_NOTIFICATION_LOCAL_TOKEN"] = ""
os.environ["TYPEX_SELF_DISPLAY_NAME"] = ""
os.environ["TRANSLATION_PROVIDER"] = "mock"
os.environ["AUTO_TRANSLATE_ENABLED"] = "true"

import pytest

from fastapi.testclient import TestClient

from app.database.base import Base
from app.database.session import get_db
from app.main import app
from app.models import AIAnalysis, Chat, Company, Contact, KnowledgeEntry, Message, MessageAttachment, MessageTranslation  # noqa: F401


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session", autouse=True)
def _dispose_app_engine() -> Generator[None, None, None]:
    yield
    from app.database.session import reset_engine

    reset_engine()


@pytest.fixture()
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
