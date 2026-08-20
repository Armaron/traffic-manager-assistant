from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database.base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def sqlite_file_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return None
    database = url.database
    if not database or database == ":memory:":
        return None
    return Path(database)


def ensure_sqlite_directory(database_url: str) -> None:
    db_path = sqlite_file_path(database_url)
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        ensure_sqlite_directory(settings.database_url)
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            connect_args["timeout"] = 30
        _engine = create_engine(
            settings.database_url,
            connect_args=connect_args,
            echo=False,
        )
        _enable_sqlite_foreign_keys(_engine)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _session_factory


def reset_engine() -> None:
    """Dispose cached engine. Used by tests when DATABASE_URL changes."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            session.close()
        except Exception:
            pass


def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    import app.models  # noqa: F401
    from app.database.upgrade import apply_schema_upgrades

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    apply_schema_upgrades(engine)
