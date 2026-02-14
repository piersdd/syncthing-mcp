"""Import all tool sub-modules so their @mcp.tool decorators run at import time."""

from syncthing_mcp.tools import config  # noqa: F401
from syncthing_mcp.tools import devices  # noqa: F401
from syncthing_mcp.tools import folders  # noqa: F401
from syncthing_mcp.tools import instances  # noqa: F401
from syncthing_mcp.tools import system  # noqa: F401
