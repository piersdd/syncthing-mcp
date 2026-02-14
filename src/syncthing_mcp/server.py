"""FastMCP server creation and lifespan."""

from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from syncthing_mcp.registry import get_all_instances


@asynccontextmanager
async def app_lifespan(app):
    import sys

    instances = get_all_instances()
    missing = [n for n, c in instances.items() if not c.api_key]
    if missing:
        print(f"WARNING: API key missing for instance(s): {missing}", file=sys.stderr)
    print(
        f"Syncthing MCP: {len(instances)} instance(s) configured — "
        f"{list(instances.keys())}",
        file=sys.stderr,
    )
    yield {}


mcp = FastMCP("syncthing_mcp", lifespan=app_lifespan)

# Import all tool modules so they register with `mcp` via decorators.
import syncthing_mcp.tools  # noqa: E402, F401
