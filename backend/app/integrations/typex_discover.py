import asyncio
import logging

from app.integrations.typex_errors import TypeXError
from app.integrations.typex_mcp import TypeXMCPClient
from app.integrations.typex_policy import allowed_read_tools, is_write_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    client = TypeXMCPClient.from_settings()
    try:
        await client.ensure_session()
    except TypeXError as exc:
        logger.error("typex_discover failed error_type=%s", type(exc).__name__)
        raise SystemExit(1) from None
    print(f"endpoint={client.base_url}")
    print(f"tools={len(client.discovered_tools)}")
    print(f"allowed_read={len(client.allowed_tool_names)}")
    for tool in client.discovered_tools:
        kind = "write" if is_write_tool(tool) else "read" if tool in allowed_read_tools([tool]) else "other"
        fields = list((tool.input_schema or {}).get("properties") or {})
        print(f"{tool.name}\tkind={kind}\tfields={fields}")
        if tool.description:
            print(f"  {tool.description[:180]}")


if __name__ == "__main__":
    asyncio.run(main())
