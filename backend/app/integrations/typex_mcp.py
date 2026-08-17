from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.typex_errors import (
    TypeXConfigurationError,
    TypeXConnectionError,
    TypeXError,
    TypeXProtocolError,
    TypeXToolCallError,
    TypeXToolUnavailableError,
)
from app.integrations.typex_policy import MCPTool, configured_read_tool_names, is_write_tool

logger = logging.getLogger(__name__)

# Fallback only. Verify against the installed TypeX version before TYPEX_MODE=real.
DEFAULT_MCP_URL = "http://127.0.0.1:52222/mcp/"
PROTOCOL_VERSION = "2024-11-05"


class TypeXMCPClient:
    """Low-level TypeX Desktop MCP client. Read-only tool calls only."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
        allowed_tool_names: set[str] | None = None,
    ) -> None:
        url = base_url.strip()
        if not url:
            raise TypeXConfigurationError("TYPEX_MCP_URL is not configured")
        self.base_url = url if url.endswith("/") else f"{url}/"
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = client
        self._session_id: str | None = None
        self._rpc_id = 0
        self.discovered_tools: list[MCPTool] = []
        self._configured_allowlist = {
            name.strip() for name in (allowed_tool_names or set()) if name and name.strip()
        }

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TypeXMCPClient:
        cfg = settings or get_settings()
        return cls(
            cfg.typex_mcp_url or DEFAULT_MCP_URL,
            timeout_seconds=cfg.typex_request_timeout_seconds,
            allowed_tool_names=configured_read_tool_names(cfg),
        )

    @property
    def allowed_tool_names(self) -> set[str]:
        """Exact configured allowlist. Discovery never adds names here."""
        return set(self._configured_allowlist)

    async def health_check(self) -> bool:
        try:
            await self.ensure_session()
            return True
        except TypeXError:
            return False

    async def ensure_session(self) -> None:
        if self.discovered_tools:
            return
        await self.initialize()
        await self.list_tools()

    async def initialize(self) -> dict[str, Any]:
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "traffic-manager-assistant", "version": "0.1.0"},
            },
        )
        await self._notify("notifications/initialized")
        if not isinstance(result, dict):
            raise TypeXProtocolError("TypeX MCP unavailable")
        logger.info("typex_mcp initialize success=true")
        return result

    async def list_tools(self) -> list[MCPTool]:
        result = await self._rpc("tools/list", {})
        raw_tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(raw_tools, list):
            raise TypeXProtocolError("TypeX MCP unavailable")
        tools: list[MCPTool] = []
        for item in raw_tools:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            schema = item.get("inputSchema") or item.get("input_schema")
            tools.append(
                MCPTool(
                    name=str(item["name"]),
                    description=str(item.get("description") or ""),
                    input_schema=schema if isinstance(schema, dict) else None,
                )
            )
        self.discovered_tools = tools
        logger.info(
            "typex_mcp tools_list count=%s configured=%s success=true",
            len(tools),
            len(self._configured_allowlist),
        )
        return tools

    def tool_by_name(self, name: str) -> MCPTool | None:
        for tool in self.discovered_tools:
            if tool.name == name:
                return tool
        return None

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name not in self._configured_allowlist:
            logger.info("typex_mcp tools_call denied name=%s reason=not_configured", name)
            raise TypeXToolUnavailableError("TypeX read operation failed")
        await self.ensure_session()
        tool = self.tool_by_name(name)
        if tool is None:
            logger.info("typex_mcp tools_call denied name=%s reason=not_discovered", name)
            raise TypeXToolUnavailableError("TypeX read operation failed")
        if is_write_tool(tool):
            logger.info("typex_mcp tools_call denied name=%s reason=write_tool", name)
            raise TypeXToolUnavailableError("TypeX read operation failed")
        logger.info("typex_mcp tools_call name=%s", name)
        result = await self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        return _unwrap_tool_result(result)

    async def _notify(self, method: str) -> None:
        await self._post({"jsonrpc": "2.0", "method": method})

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._rpc_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._rpc_id, "method": method}
        if params is not None:
            payload["params"] = params
        body = await self._post(payload)
        if not isinstance(body, dict):
            raise TypeXProtocolError("TypeX MCP unavailable")
        if body.get("error"):
            raise TypeXProtocolError("TypeX MCP unavailable")
        return body.get("result")

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        close = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            close = True
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            response = await client.post(self.base_url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise TypeXConnectionError("TypeX is not connected") from exc
        except httpx.RequestError as exc:
            raise TypeXConnectionError("TypeX is not connected") from exc
        finally:
            if close:
                await client.aclose()

        session = response.headers.get("mcp-session-id")
        if session:
            self._session_id = session
        if response.status_code >= 400:
            raise TypeXConnectionError("TypeX is not connected")
        if not response.content:
            return None
        return _parse_mcp_body(response)


def _parse_mcp_body(response: httpx.Response) -> dict[str, Any]:
    content_type = (response.headers.get("content-type") or "").lower()
    text = response.text
    if "text/event-stream" in content_type:
        for line in text.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if not chunk:
                    continue
                try:
                    parsed = json.loads(chunk)
                except json.JSONDecodeError as exc:
                    raise TypeXProtocolError("TypeX MCP unavailable") from exc
                if isinstance(parsed, dict):
                    return parsed
        raise TypeXProtocolError("TypeX MCP unavailable")
    try:
        parsed = response.json()
    except ValueError as exc:
        raise TypeXProtocolError("TypeX MCP unavailable") from exc
    if not isinstance(parsed, dict):
        raise TypeXProtocolError("TypeX MCP unavailable")
    return parsed


def _unwrap_tool_result(result: Any) -> Any:
    if result is None:
        return None
    if isinstance(result, dict) and result.get("isError") is True:
        logger.info("typex_mcp tools_call isError=true")
        raise TypeXToolCallError("TypeX MCP unavailable")
    if isinstance(result, dict) and result.get("structuredContent") is not None:
        return result["structuredContent"]
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        texts: list[str] = []
        for item in result["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(str(item.get("text") or ""))
        merged = "\n".join(part for part in texts if part)
        if merged:
            try:
                return json.loads(merged)
            except json.JSONDecodeError:
                return {"text": merged}
    return result
