"""
Syncthing MCP Server

An MCP server for interacting with the Syncthing REST API.
Provides tools for querying folder status, device connections,
and replication completeness — designed to help identify which
folders are safely replicated and can be removed locally to
free disk space.

Configuration via environment variables:
    SYNCTHING_API_KEY  - Required. API key for Syncthing REST API.
    SYNCTHING_URL      - Optional. Base URL (default: http://localhost:8384)
"""

import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SYNCTHING_URL = os.environ.get("SYNCTHING_URL", "http://localhost:8384").rstrip("/")
SYNCTHING_API_KEY = os.environ.get("SYNCTHING_API_KEY", "")

# ---------------------------------------------------------------------------
# HTTP client helpers
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": SYNCTHING_API_KEY,
        "Accept": "application/json",
    }


async def _get(path: str, params: dict | None = None) -> Any:
    """Perform an authenticated GET against the Syncthing REST API."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{SYNCTHING_URL}{path}",
            headers=_headers(),
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def _post(path: str, params: dict | None = None, body: Any = None) -> Any:
    """Perform an authenticated POST against the Syncthing REST API."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SYNCTHING_URL}{path}",
            headers=_headers(),
            params=params,
            json=body,
        )
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return {"status": "ok"}


def _handle_api_error(e: Exception) -> str:
    """Consistent error formatting."""
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 401:
            return "Error 401: Unauthorized. Check SYNCTHING_API_KEY is correct."
        if status == 403:
            return "Error 403: Forbidden. API key may lack permissions."
        if status == 404:
            return f"Error 404: Not found. Check the folder/device ID. Detail: {e.response.text}"
        return f"Error {status}: {e.response.text}"
    if isinstance(e, httpx.ConnectError):
        return f"Error: Cannot connect to Syncthing at {SYNCTHING_URL}. Is it running?"
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. Syncthing may be busy or unreachable."
    return f"Error: {type(e).__name__}: {e}"


def _format_bytes(n: int) -> str:
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ---------------------------------------------------------------------------
# Lifespan — validate connectivity on startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def app_lifespan():
    if not SYNCTHING_API_KEY:
        print("WARNING: SYNCTHING_API_KEY is not set. API calls will fail.")
    yield {}


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("syncthing_mcp", lifespan=app_lifespan)


# ===== Input Models =====


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID (e.g. 'abcd-1234')", min_length=1)


class DeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(..., description="Syncthing device ID (long alphanumeric string with dashes)", min_length=1)


class FolderDeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    device_id: str = Field(..., description="Syncthing device ID", min_length=1)


class PauseFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID to pause", min_length=1)


# ===== Tools =====


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
        status = await _get("/rest/system/status")
        version = await _get("/rest/system/version")
        config = await _get("/rest/config")
        # Find local device name
        my_id = status.get("myID", "")
        my_name = my_id[:8]
        for dev in config.get("devices", []):
            if dev.get("deviceID") == my_id:
                my_name = dev.get("name", my_id[:8])
                break
        return json.dumps(
            {
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
        return _handle_api_error(e)


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
        config = await _get("/rest/config")
        folders = config.get("folders", [])
        devices = {d["deviceID"]: d.get("name", d["deviceID"][:8]) for d in config.get("devices", [])}

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
        return _handle_api_error(e)


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
        config = await _get("/rest/config")
        connections = await _get("/rest/system/connections")
        stats = await _get("/rest/stats/device")
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
        return _handle_api_error(e)


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
        status = await _get("/rest/db/status", params={"folder": params.folder_id})
        stats = await _get("/rest/stats/folder")
        folder_stats = stats.get(params.folder_id, {})

        return json.dumps(
            {
                "folder": params.folder_id,
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
        return _handle_api_error(e)


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
        config = await _get("/rest/config")
        connections = await _get("/rest/system/connections")
        conn_data = connections.get("connections", {})
        status = await _get("/rest/system/status")
        my_id = status.get("myID", "")

        # Find the folder config
        folder_cfg = None
        for f in config.get("folders", []):
            if f["id"] == params.folder_id:
                folder_cfg = f
                break
        if not folder_cfg:
            return json.dumps({"error": f"Folder '{params.folder_id}' not found in config."})

        devices_map = {d["deviceID"]: d.get("name", d["deviceID"][:8]) for d in config.get("devices", [])}

        completions = []
        for dev in folder_cfg.get("devices", []):
            did = dev.get("deviceID", "")
            if did == my_id:
                continue  # skip self
            try:
                comp = await _get(
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
            1 for c in completions if c.get("completion") == 100 and c.get("remoteState") == "valid"
        )

        return json.dumps(
            {
                "folder": params.folder_id,
                "label": folder_cfg.get("label", params.folder_id),
                "totalRemoteDevices": len(completions),
                "fullyReplicatedOn": fully_replicated_count,
                "devices": completions,
            },
            indent=2,
        )
    except Exception as e:
        return _handle_api_error(e)


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
        config = await _get("/rest/config")
        connections = await _get("/rest/system/connections")
        conn_data = connections.get("connections", {})
        status = await _get("/rest/system/status")
        my_id = status.get("myID", "")
        devices_map = {d["deviceID"]: d.get("name", d["deviceID"][:8]) for d in config.get("devices", [])}

        folders = config.get("folders", [])
        report = []
        total_reclaimable = 0

        for folder_cfg in folders:
            fid = folder_cfg["id"]
            label = folder_cfg.get("label", fid)
            paused = folder_cfg.get("paused", False)

            # Get local folder status
            try:
                fstatus = await _get("/rest/db/status", params={"folder": fid})
            except Exception:
                report.append(
                    {
                        "folder": fid,
                        "label": label,
                        "error": "Could not get folder status.",
                    }
                )
                continue

            local_bytes = fstatus.get("localBytes", 0)
            global_bytes = fstatus.get("globalBytes", 0)
            state = fstatus.get("state", "unknown")

            # Check completion on each remote device
            remote_devices = [
                d for d in folder_cfg.get("devices", []) if d.get("deviceID") != my_id
            ]

            device_completions = []
            for dev in remote_devices:
                did = dev.get("deviceID", "")
                connected = conn_data.get(did, {}).get("connected", False)
                try:
                    comp = await _get(
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
                    "fullyReplicatedDevices": [
                        d["deviceName"] for d in fully_replicated
                    ],
                    "safeToRemove": safe,
                    "devices": device_completions,
                }
            )

        # Sort: safe-to-remove folders first, then by size descending
        report.sort(key=lambda x: (-int(x.get("safeToRemove", False)), -x.get("localBytes", 0)))

        return json.dumps(
            {
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
        return _handle_api_error(e)


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
        # Get current folder config
        folder_cfg = await _get(f"/rest/config/folders/{params.folder_id}")
        folder_cfg["paused"] = True
        # PATCH the folder config
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{SYNCTHING_URL}/rest/config/folders/{params.folder_id}",
                headers=_headers(),
                json=folder_cfg,
            )
            resp.raise_for_status()
        return json.dumps(
            {
                "status": "paused",
                "folder": params.folder_id,
                "message": f"Folder '{params.folder_id}' is now paused. "
                "Syncthing will NOT sync changes (including deletions) for this folder. "
                "You can now safely remove the local data without affecting remote copies.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_api_error(e)


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
        folder_cfg = await _get(f"/rest/config/folders/{params.folder_id}")
        folder_type = folder_cfg.get("type", "sendreceive")
        folder_cfg["paused"] = False
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{SYNCTHING_URL}/rest/config/folders/{params.folder_id}",
                headers=_headers(),
                json=folder_cfg,
            )
            resp.raise_for_status()
        return json.dumps(
            {
                "status": "resumed",
                "folder": params.folder_id,
                "folderType": folder_type,
                "message": f"Folder '{params.folder_id}' is now active again (type: {folder_type}).",
                "warning": "If local data was deleted while paused, behaviour depends on folder type: "
                "'sendreceive' may propagate deletions to peers; "
                "'receiveonly' will re-download missing files.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_api_error(e)


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
        comp = await _get("/rest/db/completion", params={"device": params.device_id})
        return json.dumps(
            {
                "deviceID": params.device_id,
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
        return _handle_api_error(e)


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
        connections = await _get("/rest/system/connections")
        config = await _get("/rest/config")
        devices_map = {d["deviceID"]: d.get("name", d["deviceID"][:8]) for d in config.get("devices", [])}

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
        return _handle_api_error(e)


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
        errors = await _get("/rest/folder/errors", params={"folder": params.folder_id})
        return json.dumps(
            {
                "folder": params.folder_id,
                "errorCount": len(errors.get("errors", []) or []),
                "errors": errors.get("errors", []),
                "page": errors.get("page", 1),
            },
            indent=2,
        )
    except Exception as e:
        return _handle_api_error(e)


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
        await _post("/rest/db/scan", params={"folder": params.folder_id})
        return json.dumps(
            {
                "status": "scan_requested",
                "folder": params.folder_id,
                "message": "Scan initiated. Folder status will update shortly.",
            },
            indent=2,
        )
    except Exception as e:
        return _handle_api_error(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
