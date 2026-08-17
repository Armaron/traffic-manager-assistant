"""TypeX adapter.

Mock conversations land in Phase 3 via MockTypeXAdapter.

Real access (Phase 8) must use official TypeX Desktop MCP only:
enable MCP in TypeX Desktop, then connect to http://127.0.0.1:52222/mcp/.
Bot API is not enough: it sees bot chats, not the user's full inbox.
Never scrape the TypeX UI.
"""

from app.enums import Platform
from app.integrations.base import MessengerAdapter


class TypeXAdapter(MessengerAdapter):
    platform = Platform.TYPEX
