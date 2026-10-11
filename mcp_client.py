"""MCP client: launches the Gmail MCP server over stdio and exposes its tools.
The whole MCP connection lives inside ONE background task (anyio requires that
the task that enters the context is the one that exits it)."""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = str(Path(__file__).parent / "gmail_server.py")


class MCPGmail:
    async def start(self):
        self._ready, self._stop, self._error = asyncio.Event(), asyncio.Event(), None
        self._task = asyncio.create_task(self._run())
        await self._ready.wait()
        if self._error:
            raise RuntimeError(f"Could not start Gmail MCP server: {self._error!r}")

    async def _run(self):
        try:
            params = StdioServerParameters(command=sys.executable, args=[SERVER])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    # MCP tool schema -> OpenAI/OpenRouter function-calling schema
                    self.openai_tools = [{"type": "function", "function": {
                        "name": t.name, "description": t.description or "",
                        "parameters": t.inputSchema}} for t in tools]
                    self.session = session
                    self._ready.set()
                    await self._stop.wait()
        except BaseException as e:
            self._error = e
            self._ready.set()

    async def call_tool(self, name: str, args: dict) -> str:
        res = await self.session.call_tool(name, args)
        text = "\n".join(c.text for c in res.content if getattr(c, "text", None)) or "ok"
        return ("ERROR: " + text if res.isError else text)[:8000]

    async def stop(self):
        self._stop.set()
        await self._task
