"""Interactive Telegram user authorization. Does not read chats or messages.

Usage (from backend/ with venv active):

    python -m app.integrations.telegram_auth
"""

from __future__ import annotations

import asyncio
import getpass
import logging
import sys

from app.config import DATA_DIR, get_settings
from app.integrations.telegram_client import resolve_session_path, telegram_missing_configuration
from app.integrations.telegram_errors import TelegramConfigurationError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _prompt_phone() -> str:
    return input("Phone (international format): ").strip()


def _prompt_code() -> str:
    return input("Telegram login code: ").strip()


def _prompt_password() -> str:
    return getpass.getpass("Two-factor password (if prompted, otherwise leave empty): ")


async def authorize() -> int:
    settings = get_settings()
    missing = telegram_missing_configuration(settings)
    if missing:
        raise TelegramConfigurationError("Telegram configuration required")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    session_path = resolve_session_path(settings.telegram_session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    from telethon import TelegramClient

    client = TelegramClient(
        str(session_path),
        int(settings.telegram_api_id),  # type: ignore[arg-type]
        str(settings.telegram_api_hash),
    )
    try:
        await client.start(
            phone=_prompt_phone,
            code_callback=_prompt_code,
            password=_prompt_password,
        )
        me = await client.get_me()
        account_id = getattr(me, "id", None)
        print("Telegram authorization successful.")
        if account_id is not None:
            print(f"Account id: {account_id}")
        return 0
    finally:
        await client.disconnect()


def main() -> int:
    try:
        return asyncio.run(authorize())
    except TelegramConfigurationError:
        print("Telegram configuration required.", file=sys.stderr)
        print("Set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_SESSION_PATH in .env.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Authorization cancelled.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
