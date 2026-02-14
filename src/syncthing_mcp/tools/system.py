"""System status, health, errors, log, restart, and upgrade tools."""

import json
from typing import Any

import httpx

from syncthing_mcp.models import EmptyInput
from syncthing_mcp.registry import (
    format_bytes,
    get_instance,
    handle_error_global,
)
from syncthing_mcp.server import mcp


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
        client = get_instance(params.instance)
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
            return handle_error_global(e)
        try:
            return get_instance(None).handle_error(e)
        except Exception:
            return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
        events = await client._get(
            "/rest/events",
            params={
                "events": "LocalChangeDetected,RemoteChangeDetected",
                "limit": "50",
                "timeout": "0",
            },
        )
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
        result = await client._get("/rest/config/restart-required")
        return json.dumps(
            {
                "instance": client.name,
                "restartRequired": result.get("requiresRestart", False),
            },
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)


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
        client = get_instance(params.instance)
        try:
            await client._post("/rest/system/restart")
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            pass  # Expected — Syncthing closes the connection as it restarts
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
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_check_upgrade",
    annotations={
        "title": "Check for Upgrade",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_check_upgrade(params: EmptyInput) -> str:
    """Check if a newer version of Syncthing is available.

    Returns:
        str: JSON with running version, latest version, and whether an upgrade
             is available.
    """
    try:
        client = get_instance(params.instance)
        version = await client._get("/rest/system/version")
        try:
            upgrade = await client._get("/rest/system/upgrade")
            return json.dumps(
                {
                    "instance": client.name,
                    "running": version.get("version"),
                    "latest": upgrade.get("latest"),
                    "newer": upgrade.get("newer", False),
                    "majorNewer": upgrade.get("majorNewer", False),
                },
                indent=2,
            )
        except httpx.HTTPStatusError as ue:
            if ue.response.status_code == 501:
                return json.dumps(
                    {
                        "instance": client.name,
                        "running": version.get("version"),
                        "message": "Upgrade check not available (disabled or unsupported).",
                    },
                    indent=2,
                )
            raise
    except Exception as e:
        return handle_error_global(e)


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
        client = get_instance(params.instance)

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

        online_count = sum(1 for c in conn_data.values() if c.get("connected"))
        total_remote = len(conn_data)

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
                    entry["needSize"] = format_bytes(fstatus.get("needBytes", 0))
                    if state in ("syncing", "sync-preparing"):
                        syncing_count += 1
                    elif state == "error":
                        error_folders += 1
                except Exception:
                    entry["state"] = "unreachable"
                    error_folders += 1
            folder_health.append(entry)

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
        return handle_error_global(e)
