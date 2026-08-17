from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_SQLITE_PATH = DATA_DIR / "traffic_manager.db"


def default_database_url() -> str:
    return "sqlite:///" + DEFAULT_SQLITE_PATH.resolve().as_posix()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Traffic Manager Assistant"
    app_env: str = "development"
    app_version: str = "0.1.0"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    typex_mode: str = "mock"
    typex_mcp_url: str = "http://127.0.0.1:52222/mcp/"
    typex_request_timeout_seconds: float = 15.0
    typex_sync_chat_limit: int = 20
    typex_sync_message_limit: int = 50
    # Exact TypeX MCP tool names. Fill after discovery. Do not guess.
    typex_chats_tool: str | None = None
    typex_messages_tool: str | None = None
    typex_current_user_tool: str | None = None
    typex_sender_tool: str | None = None
    telegram_mode: str = "mock"
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session_path: str | None = "data/telegram.session"
    telegram_sync_chat_limit: int = 20
    telegram_sync_message_limit: int = 50
    ai_provider: str = "mock"
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 30.0
    database_url: str = Field(default_factory=default_database_url)

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def _empty_telegram_api_id(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @field_validator("telegram_api_hash", "telegram_session_path", mode="before")
    @classmethod
    def _empty_telegram_str(cls, value: object) -> object:
        if value == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
