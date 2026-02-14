"""
Syncthing MCP Server

An MCP server for interacting with one or more Syncthing instances via their
REST API.  Provides tools for querying folder status, device connections,
replication completeness, config mutation (accept/reject pending, restart,
ignore patterns), and expanded monitoring.

Configuration via environment variables:

  Single instance (backward-compatible):
    SYNCTHING_API_KEY  - Required. API key for Syncthing REST API.
    SYNCTHING_URL      - Optional. Base URL (default: http://localhost:8384)

  Multiple instances:
    SYNCTHING_INSTANCES - JSON object mapping instance names to config:
      {
        "mini":  {"url": "http://mini.local:8384",  "api_key": "xxx"},
        "tn-sb": {"url": "http://tn-sb.local:8384", "api_key": "yyy"}
      }
    When set, SYNCTHING_URL and SYNCTHING_API_KEY are ignored.
"""

import json
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Syncthing HTTP Client
# ---------------------------------------------------------------------------


class SyncthingClient:
    """HTTP client for a single Syncthing instance."""

    def __init__(self, name: str, url: str, api_key: str) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any:
        """Authenticated GET against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.url}{path}",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, params: dict | None = None, body: Any = None) -> Any:
        """Authenticated POST against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.url}{path}",
                headers=self._headers(),
                params=params,
                json=body,
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json") and resp.content:
                return resp.json()
            return {"status": "ok"}

    async def _patch(self, path: str, body: Any = None) -> Any:
        """Authenticated PATCH against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{self.url}{path}",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json") and resp.content:
                return resp.json()
            return {"status": "ok"}

    async def _put(self, path: str, body: Any = None) -> Any:
        """Authenticated PUT against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"{self.url}{path}",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json") and resp.content:
                return resp.json()
            return {"status": "ok"}

    async def _delete(self, path: str, params: dict | None = None) -> Any:
        """Authenticated DELETE against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{self.url}{path}",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json") and resp.content:
                return resp.json()
            return {"status": "ok"}

    def handle_error(self, e: Exception) -> str:
        """Consistent error formatting referencing this instance."""
        prefix = f"[{self.name}] " if self.name != "default" else ""
        if isinstance(e, httpx.HTTPStatusError):
            status = e.response.status_code
            if status == 401:
                return f"{prefix}Error 401: Unauthorized. Check API key for instance '{self.name}'."
            if status == 403:
                return f"{prefix}Error 403: Forbidden. API key may lack permissions."
            if status == 404:
                return f"{prefix}Error 404: Not found. Check the folder/device ID. Detail: {e.response.text}"
            return f"{prefix}Error {status}: {e.response.text}"
        if isinstance(e, httpx.ConnectError):
            return f"{prefix}Error: Cannot connect to Syncthing at {self.url}. Is it running?"
        if isinstance(e, httpx.TimeoutException):
            return f"{prefix}Error: Request timed out. Syncthing may be busy or unreachable."
        return f"{prefix}Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Instance registry
# ---------------------------------------------------------------------------


def _format_bytes(n: int) -> str:
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _load_instances() -> dict[str, SyncthingClient]:
    """Build instance registry from environment variables."""
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


_instances: dict[str, SyncthingClient] = _load_instances()


def _get_instance(instance: str | None = None) -> SyncthingClient:
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


def _handle_error_global(e: Exception) -> str:
    """Fallback error handler when instance cannot be determined."""
    if isinstance(e, ValueError):
        return f"Error: {e}"
    return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def app_lifespan(app):
    import sys

    missing = [n for n, c in _instances.items() if not c.api_key]
    if missing:
        print(f"WARNING: API key missing for instance(s): {missing}", file=sys.stderr)
    print(
        f"Syncthing MCP: {len(_instances)} instance(s) configured — "
        f"{list(_instances.keys())}",
        file=sys.stderr,
    )
    yield {}


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("syncthing_mcp", lifespan=app_lifespan)


# ===== Input Models =====


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance: str | None = Field(
        None, description="Instance name. Omit if only one instance is configured."
    )


class FolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Syncthing folder ID (e.g. 'abcd-1234')", min_length=1
    )
    instance: str | None = Field(None, description="Instance name")


class DeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ...,
        description="Syncthing device ID (long alphanumeric string with dashes)",
        min_length=1,
    )
    instance: str | None = Field(None, description="Instance name")


class FolderDeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    device_id: str = Field(..., description="Syncthing device ID", min_length=1)
    instance: str | None = Field(None, description="Instance name")


class PauseFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Syncthing folder ID to pause/resume", min_length=1
    )
    instance: str | None = Field(None, description="Instance name")


class AcceptDeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ..., description="Device ID to accept (from pending list)", min_length=1
    )
    name: str | None = Field(
        None,
        description="Friendly name to assign. If omitted, uses the name from the pending request.",
    )
    instance: str | None = Field(None, description="Instance name")


class AcceptFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Folder ID to accept (from pending list)", min_length=1
    )
    path: str | None = Field(
        None,
        description="Local path for the folder. If omitted, uses Syncthing's default path.",
    )
    instance: str | None = Field(None, description="Instance name")


class RejectFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Folder ID to reject", min_length=1
    )
    device_id: str | None = Field(
        None,
        description="Device ID that offered the folder. If omitted, rejects from all devices.",
    )
    instance: str | None = Field(None, description="Instance name")


class SetIgnoresInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Folder ID", min_length=1)
    patterns: list[str] = Field(
        ...,
        description="List of ignore patterns (e.g. ['*.tmp', '.DS_Store', '// #include'])",
    )
    instance: str | None = Field(None, description="Instance name")


class SetDefaultIgnoresInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[str] = Field(
        ...,
        description="Default ignore patterns for new folders (e.g. ['.DS_Store', 'Thumbs.db'])",
    )
    instance: str | None = Field(None, description="Instance name")


# =====================================================================
#  TOOLS — Instance Management
# =====================================================================


@mcp.tool(
    name="syncthing_list_instances",
    annotations={
        "title": "List Configured Instances",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_list_instances(params: EmptyInput) -> str:
    """List all configured Syncthing instances and probe their availability.

    Returns:
        str: JSON array with instance name, URL, availability, and device ID.
    """
    results = []
    for name, client in _instances.items():
        entry: dict[str, Any] = {"name": name, "url": client.url}
        try:
            status = await client._get("/rest/system/status")
            version = await client._get("/rest/system/version")
            config = await client._get("/rest/config")
            my_id = status.get("myID", "")
            my_name = my_id[:8]
            for dev in config.get("devices", []):
                if dev.get("deviceID") == my_id:
                    my_name = dev.get("name", my_id[:8])
                    break
            entry.update(
                {
                    "available": True,
                    "myID": my_id,
                    "deviceName": my_name,
                    "version": version.get("version"),
                    "numFolders": len(config.get("folders", [])),
                    "numDevices": len(config.get("devices", [])),
                }
            )
        except Exception as exc:
            entry.update({"available": False, "error": str(exc)})
        results.append(entry)
    return json.dumps(results, indent=2)


# =====================================================================
#  TOOLS — System Status & Info (existing, refactored)
# =====================================================================


@mcp.tool(
    name="syncthing_system_status",
    annotations={
        "title": "System Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_system_status(params: EmptyInput) -> str:
    """Get Syncthing system status including this device's ID, name, uptime, and version.

    Returns:
        str: JSON with myID, device name, uptime, version, and connection stats.
    """
    try:
        client = _get_instance(params.instance)
        status = await client._get("/rest/system/status")
        version = await client._get("/rest/system/version")
        config = await client._get("/rest/config")
        my_id = status.get("myID", "")
        my_name = my_id[:8]
        for dev in config.get("devices", []):
            if dev.get("deviceID") == my_id:
                my_name = dev.get("name", my_id[:8])
                break
        return json.dumps(
            {
                "instance": client.name,
                "myID": my_id,
                "deviceName": my_name,
                "uptime": status.get("uptime"),
                "version": version.get("version"),
                "os": version.get("os"),
                "arch": version.get("arch"),
                "numFolders": len(config.get("folders", [])),
                "numDevices": len(config.get("devices", [])),
            },
            indent=2,
        )
    except Exception as e:
        if isinstance(e, ValueError):
            return _handle_error_global(e)
        return _get_instance(None).handle_error(e) if len(_instances) == 1 else _handle_error_global(e)


@mcp.tool(
    name="syncthing_list_folders",
    annotations={
        "title": "List All Folders",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_list_folders(params: EmptyInput) -> str:
    """List all configured Syncthing folders with their labels, paths, type, and shared devices.

    Returns:
        str: JSON array of folders with id, label, path, type, paused, and list of shared device names/IDs.
    """
    try:
        client = _get_instance(params.instance)
        config = await client._get("/rest/config")
        folders = config.get("folders", [])
        devices = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }
        result = []
        for f in folders:
            shared = []
            for d in f.get("devices", []):
                did = d.get("deviceID", "")
                shared.append({"deviceID": did, "name": devices.get(did, did[:8])})
            result.append(
                {
                    "id": f["id"],
                    "label": f.get("label", f["id"]),
                    "path": f.get("path", ""),
                    "type": f.get("type", "sendreceive"),
                    "paused": f.get("paused", False),
                    "sharedWith": shared,
                    "numDevices": len(shared),
                }
            )
        return json.dumps(result, indent=2)
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_list_devices",
    annotations={
        "title": "List All Devices",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_list_devices(params: EmptyInput) -> str:
    """List all configured devices with their names, connection status, and last seen time.

    Returns:
        str: JSON array of devices with deviceID, name, connected, paused, address, lastSeen.
    """
    try:
        client = _get_instance(params.instance)
        config = await client._get("/rest/config")
        connections = await client._get("/rest/system/connections")
        stats = await client._get("/rest/stats/device")
        conn_data = connections.get("connections", {})
        result = []
        for dev in config.get("devices", []):
            did = dev["deviceID"]
            conn = conn_data.get(did, {})
            stat = stats.get(did, {})
            result.append(
                {
                    "deviceID": did,
                    "name": dev.get("name", did[:8]),
                    "connected": conn.get("connected", False),
                    "paused": conn.get("paused", False),
                    "address": conn.get("address", ""),
                    "lastSeen": stat.get("lastSeen", ""),
                    "inBytesTotal": conn.get("inBytesTotal", 0),
                    "outBytesTotal": conn.get("outBytesTotal", 0),
                }
            )
        return json.dumps(result, indent=2)
    except Exception as e:
        return _handle_error_global(e)


# =====================================================================
#  TOOLS — Folder Status & Replication (existing, refactored)
# =====================================================================


@mcp.tool(
    name="syncthing_folder_status",
    annotations={
        "title": "Folder Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_folder_status(params: FolderInput) -> str:
    """Get detailed status for a specific folder — local/global file counts, bytes, sync state.

    Note: This is an expensive call on the Syncthing side. Use sparingly.

    Args:
        params: FolderInput with folder_id.

    Returns:
        str: JSON with globalBytes, globalFiles, localBytes, localFiles, needBytes,
             needFiles, state, stateChanged, and human-readable size strings.
    """
    try:
        client = _get_instance(params.instance)
        status = await client._get("/rest/db/status", params={"folder": params.folder_id})
        stats = await client._get("/rest/stats/folder")
        folder_stats = stats.get(params.folder_id, {})
        return json.dumps(
            {
                "folder": params.folder_id,
                "instance": client.name,
                "state": status.get("state"),
                "stateChanged": status.get("stateChanged"),
                "globalFiles": status.get("globalFiles"),
                "globalBytes": status.get("globalBytes"),
                "globalSize": _format_bytes(status.get("globalBytes", 0)),
                "localFiles": status.get("localFiles"),
                "localBytes": status.get("localBytes"),
                "localSize": _format_bytes(status.get("localBytes", 0)),
                "needFiles": status.get("needFiles"),
                "needBytes": status.get("needBytes"),
                "needSize": _format_bytes(status.get("needBytes", 0)),
                "inSyncFiles": status.get("inSyncFiles"),
                "inSyncBytes": status.get("inSyncBytes"),
                "globalDeleted": status.get("globalDeleted"),
                "localDeleted": status.get("localDeleted"),
                "ignorePatterns": status.get("ignorePatterns"),
                "lastScan": folder_stats.get("lastScan", ""),
                "lastFile": folder_stats.get("lastFile", {}),
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_folder_completion",
    annotations={
        "title": "Folder Completion by Device",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_folder_completion(params: FolderInput) -> str:
    """Get the replication completion percentage for a folder across ALL devices that share it.

    This is the key tool for determining whether a folder is fully replicated
    on remote devices before removing it locally.

    Args:
        params: FolderInput with folder_id.

    Returns:
        str: JSON with folder info and per-device completion percentages,
             including whether each device is connected and has a valid remote state.
    """
    try:
        client = _get_instance(params.instance)
        config = await client._get("/rest/config")
        connections = await client._get("/rest/system/connections")
        conn_data = connections.get("connections", {})
        status = await client._get("/rest/system/status")
        my_id = status.get("myID", "")

        folder_cfg = None
        for f in config.get("folders", []):
            if f["id"] == params.folder_id:
                folder_cfg = f
                break
        if not folder_cfg:
            return json.dumps({"error": f"Folder '{params.folder_id}' not found in config."})

        devices_map = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }
        completions = []
        for dev in folder_cfg.get("devices", []):
            did = dev.get("deviceID", "")
            if did == my_id:
                continue
            try:
                comp = await client._get(
                    "/rest/db/completion",
                    params={"folder": params.folder_id, "device": did},
                )
                connected = conn_data.get(did, {}).get("connected", False)
                completions.append(
                    {
                        "deviceID": did,
                        "deviceName": devices_map.get(did, did[:8]),
                        "connected": connected,
                        "completion": round(comp.get("completion", 0), 2),
                        "globalBytes": comp.get("globalBytes", 0),
                        "globalSize": _format_bytes(comp.get("globalBytes", 0)),
                        "needBytes": comp.get("needBytes", 0),
                        "needSize": _format_bytes(comp.get("needBytes", 0)),
                        "needItems": comp.get("needItems", 0),
                        "needDeletes": comp.get("needDeletes", 0),
                        "remoteState": comp.get("remoteState", "unknown"),
                    }
                )
            except Exception:
                completions.append(
                    {
                        "deviceID": did,
                        "deviceName": devices_map.get(did, did[:8]),
                        "connected": False,
                        "completion": None,
                        "error": "Could not query completion for this device.",
                    }
                )

        fully_replicated_count = sum(
            1
            for c in completions
            if c.get("completion") == 100 and c.get("remoteState") == "valid"
        )
        return json.dumps(
            {
                "folder": params.folder_id,
                "label": folder_cfg.get("label", params.folder_id),
                "instance": client.name,
                "totalRemoteDevices": len(completions),
                "fullyReplicatedOn": fully_replicated_count,
                "devices": completions,
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_replication_report",
    annotations={
        "title": "Replication Report — Safe to Remove?",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_replication_report(params: EmptyInput) -> str:
    """Generate a comprehensive replication report for ALL folders on this device.

    For each folder, shows:
    - Local disk usage (bytes and human-readable)
    - Number of remote devices sharing it
    - How many of those have a 100% complete, valid replica
    - A 'safeToRemove' flag: True when at least one remote device has a full valid replica
    - A 'reclaimableBytes' total for folders that are safe to remove

    This is the primary tool for deciding which folders to remove to free local disk space.

    Returns:
        str: JSON with per-folder replication analysis and a summary section with
             total reclaimable space.
    """
    try:
        client = _get_instance(params.instance)
        config = await client._get("/rest/config")
        connections = await client._get("/rest/system/connections")
        conn_data = connections.get("connections", {})
        status = await client._get("/rest/system/status")
        my_id = status.get("myID", "")
        devices_map = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }

        folders = config.get("folders", [])
        report = []
        total_reclaimable = 0

        for folder_cfg in folders:
            fid = folder_cfg["id"]
            label = folder_cfg.get("label", fid)
            paused = folder_cfg.get("paused", False)

            try:
                fstatus = await client._get("/rest/db/status", params={"folder": fid})
            except Exception:
                report.append({"folder": fid, "label": label, "error": "Could not get folder status."})
                continue

            local_bytes = fstatus.get("localBytes", 0)
            global_bytes = fstatus.get("globalBytes", 0)
            state = fstatus.get("state", "unknown")

            remote_devices = [
                d for d in folder_cfg.get("devices", []) if d.get("deviceID") != my_id
            ]
            device_completions = []
            for dev in remote_devices:
                did = dev.get("deviceID", "")
                connected = conn_data.get(did, {}).get("connected", False)
                try:
                    comp = await client._get(
                        "/rest/db/completion",
                        params={"folder": fid, "device": did},
                    )
                    device_completions.append(
                        {
                            "deviceID": did,
                            "deviceName": devices_map.get(did, did[:8]),
                            "connected": connected,
                            "completion": round(comp.get("completion", 0), 2),
                            "remoteState": comp.get("remoteState", "unknown"),
                            "needBytes": comp.get("needBytes", 0),
                        }
                    )
                except Exception:
                    device_completions.append(
                        {
                            "deviceID": did,
                            "deviceName": devices_map.get(did, did[:8]),
                            "connected": connected,
                            "completion": None,
                            "remoteState": "unknown",
                        }
                    )

            fully_replicated = [
                d
                for d in device_completions
                if d.get("completion") == 100 and d.get("remoteState") == "valid"
            ]
            safe = len(fully_replicated) >= 1 and state == "idle" and not paused

            if safe:
                total_reclaimable += local_bytes

            report.append(
                {
                    "folder": fid,
                    "label": label,
                    "path": folder_cfg.get("path", ""),
                    "type": folder_cfg.get("type", "sendreceive"),
                    "paused": paused,
                    "state": state,
                    "localBytes": local_bytes,
                    "localSize": _format_bytes(local_bytes),
                    "globalBytes": global_bytes,
                    "globalSize": _format_bytes(global_bytes),
                    "totalRemoteDevices": len(remote_devices),
                    "fullyReplicatedOn": len(fully_replicated),
                    "fullyReplicatedDevices": [d["deviceName"] for d in fully_replicated],
                    "safeToRemove": safe,
                    "devices": device_completions,
                }
            )

        report.sort(key=lambda x: (-int(x.get("safeToRemove", False)), -x.get("localBytes", 0)))

        return json.dumps(
            {
                "instance": client.name,
                "summary": {
                    "totalFolders": len(report),
                    "safeToRemoveCount": sum(1 for r in report if r.get("safeToRemove")),
                    "totalReclaimableBytes": total_reclaimable,
                    "totalReclaimableSize": _format_bytes(total_reclaimable),
                },
                "folders": report,
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


# =====================================================================
#  TOOLS — Folder Operations (existing, refactored)
# =====================================================================


@mcp.tool(
    name="syncthing_pause_folder",
    annotations={
        "title": "Pause a Folder",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_pause_folder(params: PauseFolderInput) -> str:
    """Pause syncing for a specific folder. Useful before removing data locally.

    This does NOT delete data — it only pauses sync activity so you can safely
    remove the local copy without Syncthing propagating the deletion to other devices.

    Args:
        params: PauseFolderInput with folder_id.

    Returns:
        str: Confirmation message.
    """
    try:
        client = _get_instance(params.instance)
        folder_cfg = await client._get(f"/rest/config/folders/{params.folder_id}")
        folder_cfg["paused"] = True
        await client._patch(f"/rest/config/folders/{params.folder_id}", body=folder_cfg)
        return json.dumps(
            {
                "status": "paused",
                "folder": params.folder_id,
                "instance": client.name,
                "message": (
                    f"Folder '{params.folder_id}' is now paused. "
                    "Syncthing will NOT sync changes (including deletions) for this folder. "
                    "You can now safely remove the local data without affecting remote copies."
                ),
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_resume_folder",
    annotations={
        "title": "Resume a Folder",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_resume_folder(params: PauseFolderInput) -> str:
    """Resume syncing for a previously paused folder.

    WARNING: If you deleted local data while paused, resuming will cause Syncthing
    to either re-download the data (receive-only/sendreceive) or propagate deletions
    to other devices (sendreceive). Understand the folder type before resuming.

    Args:
        params: PauseFolderInput with folder_id.

    Returns:
        str: Confirmation message with warnings.
    """
    try:
        client = _get_instance(params.instance)
        folder_cfg = await client._get(f"/rest/config/folders/{params.folder_id}")
        folder_type = folder_cfg.get("type", "sendreceive")
        folder_cfg["paused"] = False
        await client._patch(f"/rest/config/folders/{params.folder_id}", body=folder_cfg)
        return json.dumps(
            {
                "status": "resumed",
                "folder": params.folder_id,
                "folderType": folder_type,
                "instance": client.name,
                "message": f"Folder '{params.folder_id}' is now active again (type: {folder_type}).",
                "warning": (
                    "If local data was deleted while paused, behaviour depends on folder type: "
                    "'sendreceive' may propagate deletions to peers; "
                    "'receiveonly' will re-download missing files."
                ),
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_scan_folder",
    annotations={
        "title": "Trigger Folder Scan",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_scan_folder(params: FolderInput) -> str:
    """Request an immediate rescan of a folder to refresh its status.

    Useful to ensure completion data is up to date before deciding to remove files.

    Args:
        params: FolderInput with folder_id.

    Returns:
        str: Confirmation that scan was requested.
    """
    try:
        client = _get_instance(params.instance)
        await client._post("/rest/db/scan", params={"folder": params.folder_id})
        return json.dumps(
            {
                "status": "scan_requested",
                "folder": params.folder_id,
                "instance": client.name,
                "message": "Scan initiated. Folder status will update shortly.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


# =====================================================================
#  TOOLS — Device Status (existing, refactored)
# =====================================================================


@mcp.tool(
    name="syncthing_device_completion",
    annotations={
        "title": "Device Completion (All Folders)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_device_completion(params: DeviceInput) -> str:
    """Get the aggregated sync completion for a specific remote device across all shared folders.

    Args:
        params: DeviceInput with device_id.

    Returns:
        str: JSON with overall completion %, globalBytes, needBytes for that device.
    """
    try:
        client = _get_instance(params.instance)
        comp = await client._get(
            "/rest/db/completion", params={"device": params.device_id}
        )
        return json.dumps(
            {
                "deviceID": params.device_id,
                "instance": client.name,
                "completion": round(comp.get("completion", 0), 2),
                "globalBytes": comp.get("globalBytes", 0),
                "globalSize": _format_bytes(comp.get("globalBytes", 0)),
                "needBytes": comp.get("needBytes", 0),
                "needSize": _format_bytes(comp.get("needBytes", 0)),
                "needItems": comp.get("needItems", 0),
                "remoteState": comp.get("remoteState", "unknown"),
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_connections",
    annotations={
        "title": "Active Connections",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_connections(params: EmptyInput) -> str:
    """Get current connection details for all devices.

    Returns:
        str: JSON with per-device connection info including address,
             bytes transferred, crypto, and connection type.
    """
    try:
        client = _get_instance(params.instance)
        connections = await client._get("/rest/system/connections")
        config = await client._get("/rest/config")
        devices_map = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }
        result = []
        for did, conn in connections.get("connections", {}).items():
            result.append(
                {
                    "deviceID": did,
                    "deviceName": devices_map.get(did, did[:8]),
                    "connected": conn.get("connected", False),
                    "paused": conn.get("paused", False),
                    "address": conn.get("address", ""),
                    "type": conn.get("type", ""),
                    "crypto": conn.get("crypto", ""),
                    "inBytesTotal": conn.get("inBytesTotal", 0),
                    "outBytesTotal": conn.get("outBytesTotal", 0),
                }
            )
        return json.dumps(result, indent=2)
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_folder_errors",
    annotations={
        "title": "Folder Errors",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_folder_errors(params: FolderInput) -> str:
    """Get current sync errors for a specific folder.

    Args:
        params: FolderInput with folder_id.

    Returns:
        str: JSON with error list and count.
    """
    try:
        client = _get_instance(params.instance)
        errors = await client._get(
            "/rest/folder/errors", params={"folder": params.folder_id}
        )
        return json.dumps(
            {
                "folder": params.folder_id,
                "instance": client.name,
                "errorCount": len(errors.get("errors", []) or []),
                "errors": errors.get("errors", []),
                "page": errors.get("page", 1),
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


# =====================================================================
#  TOOLS — Config Mutation: Pending Devices & Folders
# =====================================================================


@mcp.tool(
    name="syncthing_pending_devices",
    annotations={
        "title": "List Pending Device Requests",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_pending_devices(params: EmptyInput) -> str:
    """List remote devices that have tried to connect but are not yet configured.

    Returns:
        str: JSON object keyed by device ID, each with name, address, and time.
    """
    try:
        client = _get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/devices")
        return json.dumps(
            {"instance": client.name, "pendingDevices": pending},
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_pending_folders",
    annotations={
        "title": "List Pending Folder Offers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_pending_folders(params: EmptyInput) -> str:
    """List folders that remote devices have offered to share but are not yet accepted.

    Returns:
        str: JSON object keyed by folder ID, each listing offering devices with labels.
    """
    try:
        client = _get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/folders")
        return json.dumps(
            {"instance": client.name, "pendingFolders": pending},
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_accept_device",
    annotations={
        "title": "Accept Pending Device",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def syncthing_accept_device(params: AcceptDeviceInput) -> str:
    """Accept a pending device by adding it to the Syncthing configuration.

    The device will be added with 'dynamic' addressing. You can optionally
    provide a friendly name.

    Args:
        params: AcceptDeviceInput with device_id and optional name.

    Returns:
        str: Confirmation message with the device details.
    """
    try:
        client = _get_instance(params.instance)

        # Check it's actually pending
        pending = await client._get("/rest/cluster/pending/devices")
        pending_info = pending.get(params.device_id, {})

        # Determine name
        name = params.name
        if not name:
            name = pending_info.get("name", params.device_id[:8])

        # Get default device config as template
        defaults = await client._get("/rest/config/defaults/device")
        new_device = defaults.copy()
        new_device["deviceID"] = params.device_id
        new_device["name"] = name

        # POST single device object to /rest/config/devices
        await client._post("/rest/config/devices", body=new_device)

        return json.dumps(
            {
                "status": "accepted",
                "deviceID": params.device_id,
                "name": name,
                "instance": client.name,
                "message": f"Device '{name}' ({params.device_id[:8]}...) has been added.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_reject_device",
    annotations={
        "title": "Reject Pending Device",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_reject_device(params: DeviceInput) -> str:
    """Dismiss a pending device connection request.

    This only clears the pending notification. The device can try again later;
    for permanent blocking, use Syncthing's ignore-device feature via the web UI.

    Args:
        params: DeviceInput with device_id.

    Returns:
        str: Confirmation message.
    """
    try:
        client = _get_instance(params.instance)
        await client._delete(
            "/rest/cluster/pending/devices",
            params={"device": params.device_id},
        )
        return json.dumps(
            {
                "status": "rejected",
                "deviceID": params.device_id,
                "instance": client.name,
                "message": f"Pending device '{params.device_id[:8]}...' has been dismissed.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_accept_folder",
    annotations={
        "title": "Accept Pending Folder Offer",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def syncthing_accept_folder(params: AcceptFolderInput) -> str:
    """Accept a pending folder share offer by adding it to the configuration.

    Uses the default folder configuration as a template. If no path is provided,
    Syncthing's default folder path is used.

    Args:
        params: AcceptFolderInput with folder_id and optional path.

    Returns:
        str: Confirmation with assigned path and sharing details.
    """
    try:
        client = _get_instance(params.instance)

        # Look up pending info
        pending = await client._get("/rest/cluster/pending/folders")
        folder_pending = pending.get(params.folder_id, {})
        if not folder_pending:
            return json.dumps(
                {"error": f"Folder '{params.folder_id}' not found in pending offers."}
            )

        # Determine offering devices
        offering_devices = list(folder_pending.get("offeredBy", {}).keys())

        # Get label from the first offering device's info
        first_offer = next(iter(folder_pending.get("offeredBy", {}).values()), {})
        label = first_offer.get("label", params.folder_id)

        # Get my device ID
        status = await client._get("/rest/system/status")
        my_id = status.get("myID", "")

        # Get default folder config as template
        defaults = await client._get("/rest/config/defaults/folder")
        new_folder = defaults.copy()
        new_folder["id"] = params.folder_id
        new_folder["label"] = label

        if params.path:
            new_folder["path"] = params.path

        # Build device list: self + all offering devices
        device_list = [{"deviceID": my_id}]
        for did in offering_devices:
            device_list.append({"deviceID": did})
        new_folder["devices"] = device_list

        # POST single folder object
        await client._post("/rest/config/folders", body=new_folder)

        return json.dumps(
            {
                "status": "accepted",
                "folderID": params.folder_id,
                "label": label,
                "path": new_folder.get("path", "(default)"),
                "sharedWith": offering_devices,
                "instance": client.name,
                "message": (
                    f"Folder '{label}' ({params.folder_id}) has been added "
                    f"at '{new_folder.get('path', '(default)')}'."
                ),
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_reject_folder",
    annotations={
        "title": "Reject Pending Folder Offer",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_reject_folder(params: RejectFolderInput) -> str:
    """Dismiss a pending folder share offer.

    Args:
        params: RejectFolderInput with folder_id and optional device_id.
                If device_id is omitted, rejects the offer from all devices.

    Returns:
        str: Confirmation message.
    """
    try:
        client = _get_instance(params.instance)
        delete_params: dict[str, str] = {"folder": params.folder_id}
        if params.device_id:
            delete_params["device"] = params.device_id
        await client._delete("/rest/cluster/pending/folders", params=delete_params)
        return json.dumps(
            {
                "status": "rejected",
                "folderID": params.folder_id,
                "deviceID": params.device_id or "(all)",
                "instance": client.name,
                "message": f"Pending folder offer for '{params.folder_id}' has been dismissed.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


# =====================================================================
#  TOOLS — Config Mutation: Restart & Ignore Patterns
# =====================================================================


@mcp.tool(
    name="syncthing_restart_required",
    annotations={
        "title": "Check if Restart Required",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_restart_required(params: EmptyInput) -> str:
    """Check if Syncthing requires a restart for configuration changes to take effect.

    Returns:
        str: JSON with restartRequired boolean.
    """
    try:
        client = _get_instance(params.instance)
        result = await client._get("/rest/config/restart-required")
        return json.dumps(
            {
                "instance": client.name,
                "restartRequired": result.get("requiresRestart", False),
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_restart",
    annotations={
        "title": "Restart Syncthing",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_restart(params: EmptyInput) -> str:
    """Restart the Syncthing service to apply pending configuration changes.

    WARNING: This temporarily stops synchronization on all folders for this instance.

    Returns:
        str: Confirmation message.
    """
    try:
        client = _get_instance(params.instance)
        try:
            await client._post("/rest/system/restart")
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            # Expected — Syncthing closes the connection as it restarts
            pass
        return json.dumps(
            {
                "status": "restart_initiated",
                "instance": client.name,
                "message": (
                    f"Syncthing on '{client.name}' is restarting. "
                    "Connection may be lost briefly. Sync resumes automatically."
                ),
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_get_ignores",
    annotations={
        "title": "Get Folder Ignore Patterns",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_get_ignores(params: FolderInput) -> str:
    """Get the current .stignore patterns for a folder.

    Args:
        params: FolderInput with folder_id.

    Returns:
        str: JSON with ignore patterns list and whether the folder has expanded patterns.
    """
    try:
        client = _get_instance(params.instance)
        result = await client._get(
            "/rest/db/ignores", params={"folder": params.folder_id}
        )
        return json.dumps(
            {
                "folder": params.folder_id,
                "instance": client.name,
                "patterns": result.get("ignore", []) or [],
                "expanded": result.get("expanded", []) or [],
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_set_ignores",
    annotations={
        "title": "Set Folder Ignore Patterns",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_set_ignores(params: SetIgnoresInput) -> str:
    """Set the .stignore patterns for a folder. Replaces all existing patterns.

    Common patterns: '*.tmp', '.DS_Store', 'Thumbs.db', '(?d).Trash*',
    '// #include common-ignores' (to include shared pattern files).

    Args:
        params: SetIgnoresInput with folder_id and patterns list.

    Returns:
        str: Confirmation with the applied patterns.
    """
    try:
        client = _get_instance(params.instance)
        await client._post(
            "/rest/db/ignores",
            params={"folder": params.folder_id},
            body={"ignore": params.patterns},
        )
        return json.dumps(
            {
                "status": "updated",
                "folder": params.folder_id,
                "instance": client.name,
                "patternCount": len(params.patterns),
                "patterns": params.patterns,
                "message": f"Ignore patterns for '{params.folder_id}' have been updated.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_get_default_ignores",
    annotations={
        "title": "Get Default Ignore Patterns",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_get_default_ignores(params: EmptyInput) -> str:
    """Get the default ignore patterns applied to newly created folders.

    Returns:
        str: JSON with default ignore pattern lines.
    """
    try:
        client = _get_instance(params.instance)
        result = await client._get("/rest/config/defaults/ignores")
        return json.dumps(
            {
                "instance": client.name,
                "lines": result.get("lines", []) or [],
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_set_default_ignores",
    annotations={
        "title": "Set Default Ignore Patterns",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_set_default_ignores(params: SetDefaultIgnoresInput) -> str:
    """Set the default ignore patterns for newly created folders.

    These patterns will be automatically applied when new folders are added.

    Args:
        params: SetDefaultIgnoresInput with lines list.

    Returns:
        str: Confirmation with the applied patterns.
    """
    try:
        client = _get_instance(params.instance)
        await client._put(
            "/rest/config/defaults/ignores",
            body={"lines": params.lines},
        )
        return json.dumps(
            {
                "status": "updated",
                "instance": client.name,
                "lineCount": len(params.lines),
                "lines": params.lines,
                "message": "Default ignore patterns have been updated for new folders.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


# =====================================================================
#  TOOLS — Expanded Monitoring
# =====================================================================


@mcp.tool(
    name="syncthing_system_errors",
    annotations={
        "title": "System Errors & Warnings",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_system_errors(params: EmptyInput) -> str:
    """Get recent system errors and warnings from Syncthing.

    Returns:
        str: JSON with error list, each containing 'when' timestamp and 'message'.
    """
    try:
        client = _get_instance(params.instance)
        result = await client._get("/rest/system/error")
        errors = result.get("errors", []) or []
        return json.dumps(
            {
                "instance": client.name,
                "errorCount": len(errors),
                "errors": errors,
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_clear_errors",
    annotations={
        "title": "Clear System Errors",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_clear_errors(params: EmptyInput) -> str:
    """Clear the system error log.

    Returns:
        str: Confirmation message.
    """
    try:
        client = _get_instance(params.instance)
        await client._post("/rest/system/error/clear")
        return json.dumps(
            {
                "status": "cleared",
                "instance": client.name,
                "message": "System error log has been cleared.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_system_log",
    annotations={
        "title": "System Log",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_system_log(params: EmptyInput) -> str:
    """Get recent system log entries from Syncthing.

    Returns:
        str: JSON with log messages, each containing 'when' timestamp, 'message',
             and 'level'.
    """
    try:
        client = _get_instance(params.instance)
        result = await client._get("/rest/system/log")
        messages = result.get("messages", []) or []
        return json.dumps(
            {
                "instance": client.name,
                "messageCount": len(messages),
                "messages": messages,
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_recent_changes",
    annotations={
        "title": "Recent File Changes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_recent_changes(params: EmptyInput) -> str:
    """Get recent file change events (local and remote) across all folders.

    Uses a non-blocking poll of the Syncthing event stream with limit=50.

    Returns:
        str: JSON with recent LocalChangeDetected and RemoteChangeDetected events.
    """
    try:
        client = _get_instance(params.instance)
        events = await client._get(
            "/rest/events",
            params={
                "events": "LocalChangeDetected,RemoteChangeDetected",
                "limit": "50",
                "timeout": "0",
            },
        )
        # events is a list of event objects
        if not isinstance(events, list):
            events = []
        return json.dumps(
            {
                "instance": client.name,
                "eventCount": len(events),
                "events": events,
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


@mcp.tool(
    name="syncthing_health_summary",
    annotations={
        "title": "Health Summary",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_health_summary(params: EmptyInput) -> str:
    """Generate a single-call health overview: system status, folder states,
    device connectivity, errors, and pending items.

    Designed for quick triage — aggregates data from multiple endpoints.

    Returns:
        str: JSON with overall status ('good', 'warning', 'error'), summary
             counts, alert list, and per-folder health.
    """
    try:
        client = _get_instance(params.instance)

        # Gather data
        sys_status = await client._get("/rest/system/status")
        config = await client._get("/rest/config")
        sys_errors = await client._get("/rest/system/error")
        connections = await client._get("/rest/system/connections")

        try:
            pending_devices = await client._get("/rest/cluster/pending/devices")
        except Exception:
            pending_devices = {}
        try:
            pending_folders = await client._get("/rest/cluster/pending/folders")
        except Exception:
            pending_folders = {}

        folders = config.get("folders", [])
        conn_data = connections.get("connections", {})

        # Check device connectivity
        online_count = sum(1 for c in conn_data.values() if c.get("connected"))
        total_remote = len(conn_data)

        # Check folder states
        folder_health = []
        paused_count = 0
        syncing_count = 0
        error_folders = 0

        for f_cfg in folders:
            fid = f_cfg["id"]
            entry: dict[str, Any] = {
                "id": fid,
                "label": f_cfg.get("label", fid),
                "paused": f_cfg.get("paused", False),
            }
            if f_cfg.get("paused", False):
                paused_count += 1
                entry["state"] = "paused"
            else:
                try:
                    fstatus = await client._get(
                        "/rest/db/status", params={"folder": fid}
                    )
                    state = fstatus.get("state", "unknown")
                    entry["state"] = state
                    entry["needBytes"] = fstatus.get("needBytes", 0)
                    entry["needSize"] = _format_bytes(fstatus.get("needBytes", 0))
                    if state in ("syncing", "sync-preparing"):
                        syncing_count += 1
                    elif state == "error":
                        error_folders += 1
                except Exception:
                    entry["state"] = "unreachable"
                    error_folders += 1
            folder_health.append(entry)

        # Build alerts
        alerts: list[str] = []
        error_list = sys_errors.get("errors", []) or []
        if error_list:
            alerts.append(f"{len(error_list)} system error(s)")
        if error_folders > 0:
            alerts.append(f"{error_folders} folder(s) in error state")
        offline_count = total_remote - online_count
        if offline_count > 0:
            alerts.append(f"{offline_count} device(s) offline")
        if paused_count > 0:
            alerts.append(f"{paused_count} folder(s) paused")
        if syncing_count > 0:
            alerts.append(f"{syncing_count} folder(s) currently syncing")
        num_pending_dev = len(pending_devices) if isinstance(pending_devices, dict) else 0
        num_pending_fld = len(pending_folders) if isinstance(pending_folders, dict) else 0
        if num_pending_dev > 0:
            alerts.append(f"{num_pending_dev} pending device request(s)")
        if num_pending_fld > 0:
            alerts.append(f"{num_pending_fld} pending folder offer(s)")

        # Overall status
        if error_folders > 0 or len(error_list) > 0:
            overall = "error"
        elif alerts:
            overall = "warning"
        else:
            overall = "good"

        return json.dumps(
            {
                "instance": client.name,
                "status": overall,
                "uptime": sys_status.get("uptime"),
                "summary": {
                    "totalFolders": len(folders),
                    "foldersIdle": sum(
                        1 for f in folder_health if f.get("state") == "idle"
                    ),
                    "foldersSyncing": syncing_count,
                    "foldersPaused": paused_count,
                    "foldersError": error_folders,
                    "totalDevices": len(config.get("devices", [])),
                    "devicesOnline": online_count,
                    "devicesOffline": offline_count,
                    "systemErrors": len(error_list),
                    "pendingDevices": num_pending_dev,
                    "pendingFolders": num_pending_fld,
                },
                "alerts": alerts,
                "folders": folder_health,
            },
            indent=2,
        )
    except Exception as e:
        return _handle_error_global(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
