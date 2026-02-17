"""Instance registry — load Syncthing instances from environment variables."""

import json
import os

from syncthing_mcp.client import SyncthingClient


def format_bytes(n: int) -> str:
    """Human-readable byte size.  Delegates to formatters.format_bytes."""
    from syncthing_mcp.formatters import format_bytes as _fb

    return _fb(n)


def load_instances() -> dict[str, SyncthingClient]:
    """Build instance registry from environment variables.

    Supports two modes:
      - Multi-instance via SYNCTHING_INSTANCES (JSON object)
      - Single-instance via SYNCTHING_API_KEY + SYNCTHING_URL
    """
    instances_json = os.environ.get("SYNCTHING_INSTANCES", "").strip()

    if instances_json:
        try:
            cfg = json.loads(instances_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid SYNCTHING_INSTANCES JSON: {exc}") from exc
        if not isinstance(cfg, dict) or not cfg:
            raise ValueError("SYNCTHING_INSTANCES must be a non-empty JSON object.")
        instances: dict[str, SyncthingClient] = {}
        for name, entry in cfg.items():
            if not isinstance(entry, dict):
                raise ValueError(f"Instance '{name}' config must be a JSON object.")
            url = entry.get("url", "http://localhost:8384")
            api_key = entry.get("api_key", "")
            instances[name] = SyncthingClient(name, url, api_key)
        return instances

    # Backward-compatible single-instance fallback
    url = os.environ.get("SYNCTHING_URL", "http://localhost:8384")
    api_key = os.environ.get("SYNCTHING_API_KEY", "")
    return {"default": SyncthingClient("default", url, api_key)}


# Module-level registry, initialised at import time.
_instances: dict[str, SyncthingClient] = load_instances()


def get_instance(instance: str | None = None) -> SyncthingClient:
    """Resolve an instance by name, or auto-select when there is only one."""
    if instance is None:
        if len(_instances) == 1:
            return next(iter(_instances.values()))
        names = list(_instances.keys())
        raise ValueError(
            f"Multiple instances configured ({names}). "
            "Specify 'instance' parameter to choose one."
        )
    if instance not in _instances:
        raise ValueError(
            f"Instance '{instance}' not found. Available: {list(_instances.keys())}"
        )
    return _instances[instance]


def get_all_instances() -> dict[str, SyncthingClient]:
    """Return the full instance registry."""
    return _instances


def handle_error_global(e: Exception) -> str:
    """Fallback error handler when instance cannot be determined."""
    if isinstance(e, ValueError):
        return f"Error: {e}"
    return f"Error: {type(e).__name__}: {e}"


def reload_instances() -> None:
    """Re-read environment and rebuild the instance registry (for testing)."""
    global _instances
    _instances = load_instances()
