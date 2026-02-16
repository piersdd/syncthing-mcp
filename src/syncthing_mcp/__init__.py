"""Syncthing MCP Server — manage Syncthing instances via MCP tools."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("syncthing-mcp")
except PackageNotFoundError:
    __version__ = "0.2.0"  # fallback for editable installs / development
