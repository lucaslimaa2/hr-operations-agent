"""
In-process session adapter for FastMCP servers.

Background
----------
The orchestrator's "real" mode launches each MCP server as a subprocess and
talks to it over stdio. That's correct in a long-running server (Railway,
Fly.io) where the subprocess survives for the lifetime of the host.

On Vercel's Python serverless runtime, that pattern breaks:
  - Each invocation spawns a fresh container.
  - Spawning `python -m mcp_servers.X` from inside the container fails:
    Vercel packages dependencies under `/var/task/_vendor/` and the parent
    PYTHONPATH isn't reliably inherited by the child Python process, so
    the spawned server can't import `mcp_servers` or its deps. The MCP
    stdio handshake then fails with `McpError: Connection closed`.

The fix is to skip the subprocess + stdio layer entirely on serverless and
call the FastMCP tool functions in-process. Same tools, same args, same
return shapes — just delivered via direct method calls instead of a
JSON-RPC pipe.

This adapter exposes the subset of `mcp.ClientSession`'s interface that the
orchestrator actually uses:
  - `initialize()`     no-op
  - `list_tools()`     -> ListToolsResult-shaped object with `.tools`
  - `call_tool()`      -> CallToolResult-shaped object with `.content` + `.isError`

The orchestrator can use these interchangeably with the real ClientSession.

Architectural framing for recruiters
------------------------------------
This isn't "abandoning MCP." The MCP boundary is still the abstraction —
tools are defined in MCP servers, the orchestrator only knows about tool
names and schemas, the conflict resolver and audit log are transport-agnostic.
What changes per environment is *transport*: stdio subprocess for long-running
hosts, in-process for serverless. Same logical contract, environment-appropriate
implementation. This is the same kind of decision you'd make choosing gRPC vs
HTTP vs in-process function calls for inter-service communication.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mcp.server.fastmcp import FastMCP

# Import each MCP server module — these define `mcp = FastMCP(...)` at module
# scope plus their @mcp.tool() functions. Importing is enough to register them.
from mcp_servers.hris_server import mcp as _hris_mcp
from mcp_servers.jurisdiction_server import mcp as _jurisdiction_mcp
from mcp_servers.policy_server import mcp as _policy_mcp

# Registry: agent_name -> FastMCP server instance.
# Mirror of orchestrator.MCP_SERVERS but for in-process use.
INPROCESS_SERVERS: dict[str, FastMCP] = {
    "jurisdiction": _jurisdiction_mcp,
    "hris": _hris_mcp,
    "policy": _policy_mcp,
}


class InProcessSession:
    """Wraps a FastMCP server instance and exposes the ClientSession subset that
    the orchestrator uses (initialize, list_tools, call_tool).

    Return shapes match what stdio ClientSession returns, so the orchestrator
    code is unchanged whether it's talking to a subprocess or to one of these.
    """

    def __init__(self, mcp_server: FastMCP) -> None:
        self._mcp = mcp_server

    async def initialize(self) -> None:
        """ClientSession does an MCP handshake here. In-process: nothing to do."""
        return None

    async def list_tools(self) -> Any:
        """Return an object with a `.tools` attribute matching ClientSession's shape."""
        tools = await self._mcp.list_tools()
        return SimpleNamespace(tools=tools)

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call the named tool in-process.

        FastMCP.call_tool returns a tuple: (content_list, structured_output_or_none).
        ClientSession's call_tool returns an object with `.content` (list of
        text/image content) and `.isError` (bool). We adapt the tuple to that shape.

        On exception, we surface it as an error tool result rather than letting
        the orchestrator's outer try/except swallow it as a TaskGroup error.
        """
        try:
            raw = await self._mcp.call_tool(name, args)
            # FastMCP returns either a list of content or a tuple. Normalize.
            if isinstance(raw, tuple):
                content = raw[0]
            else:
                content = raw
            return SimpleNamespace(content=content, isError=False)
        except Exception as e:  # noqa: BLE001
            # Build a text content shaped like FastMCP's TextContent (object
            # with `.text` attr) so the orchestrator's `c.text` access works.
            err_text = f"Tool '{name}' raised {type(e).__name__}: {e}"
            error_block = SimpleNamespace(type="text", text=err_text)
            return SimpleNamespace(content=[error_block], isError=True)
