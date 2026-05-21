from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import anyio

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from services.tool_client import LocalSimulationToolClient


class McpToolClient:
    """Hybrid MCP client with stdio first and local fallback."""

    def __init__(
        self,
        command: str,
        args: list[str],
        fallback_client: LocalSimulationToolClient,
        env: dict[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        self.command = command
        self.args = args
        self.env = env or {}
        self.cwd = Path(cwd) if cwd else None
        self.fallback_client = fallback_client

    def status(self) -> dict[str, Any]:
        available = self._command_available()
        if not available:
            return {
                "mode": "fallback",
                "available": False,
                "command": self.command,
                "args": self.args,
            }
        return {
            "mode": "stdio",
            "available": True,
            "command": self.command,
            "args": self.args,
        }

    def get_equipment_status(self) -> dict:
        return self._call_or_fallback("get_equipment_status", {}, self.fallback_client.get_equipment_status)

    def get_queue_snapshot(self) -> dict:
        return self._call_or_fallback("get_queue_snapshot", {}, self.fallback_client.get_queue_snapshot)

    def reserve_equipment_slot(
        self,
        equipment_type: str,
        order_id: str,
        start_minute: int,
        duration_minutes: int,
        sample_quantity: int,
    ) -> dict:
        return self._call_or_fallback(
            "reserve_equipment_slot",
            {
                "equipment_type": equipment_type,
                "order_id": order_id,
                "start_minute": start_minute,
                "duration_minutes": duration_minutes,
                "sample_quantity": sample_quantity,
            },
            lambda: self.fallback_client.reserve_equipment_slot(
                equipment_type=equipment_type,
                order_id=order_id,
                start_minute=start_minute,
                duration_minutes=duration_minutes,
                sample_quantity=sample_quantity,
            ),
        )

    def _command_available(self) -> bool:
        if Path(self.command).exists():
            return True
        return shutil.which(self.command) is not None

    def _call_or_fallback(self, tool_name: str, arguments: dict[str, Any], fallback_callable):
        try:
            return self._call_tool(tool_name, arguments)
        except Exception:
            return fallback_callable()

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict:
        if not self._command_available():
            raise RuntimeError("MCP command unavailable")
        return anyio.run(self._call_tool_async, tool_name, arguments)

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> dict:
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env or None,
            cwd=str(self.cwd) if self.cwd else None,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return self._decode_result(result)

    def _decode_result(self, result: Any) -> dict:
        if isinstance(result, dict):
            return result
        content = getattr(result, "content", None)
        if not content:
            return {"result": None}
        parts = []
        for item in content:
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(text)
        if parts:
            joined = "".join(parts)
            try:
                return json.loads(joined)
            except json.JSONDecodeError:
                return {"result": joined}
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        return {"result": None}
