"""Device listing, completion, connection, and stats tools."""

from typing import Any

from syncthing_mcp.formatters import fmt, format_bytes, format_connection, format_device, truncate
from syncthing_mcp.models import DeviceReadParams, ReadParams
from syncthing_mcp.registry import get_instance, handle_error_global
from syncthing_mcp.server import mcp


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
async def syncthing_list_devices(params: ReadParams) -> str:
    """All configured devices with connection status and last seen time."""
    try:
        client = get_instance(params.instance)
        config = await client._get("/rest/config")
        connections = await client._get("/rest/system/connections")
        stats = await client._get("/rest/stats/device")
        conn_data = connections.get("connections", {})
        result = [
            format_device(
                dev,
                conn_data.get(dev["deviceID"]),
                stats.get(dev["deviceID"]),
                concise=params.concise,
            )
            for dev in config.get("devices", [])
        ]
        return fmt(result, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)


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
async def syncthing_device_completion(params: DeviceReadParams) -> str:
    """Aggregated sync completion for a remote device across all shared folders."""
    try:
        client = get_instance(params.instance)
        comp = await client._get(
            "/rest/db/completion", params={"device": params.device_id}
        )
        data: dict[str, Any] = {
            "device": params.device_id[:8] if params.concise else params.device_id,
            "instance": client.name,
            "completion": round(comp.get("completion", 0), 2),
            "needSize": format_bytes(comp.get("needBytes", 0)),
            "remoteState": comp.get("remoteState", "unknown"),
        }
        if not params.concise:
            data["globalBytes"] = comp.get("globalBytes", 0)
            data["globalSize"] = format_bytes(comp.get("globalBytes", 0))
            data["needBytes"] = comp.get("needBytes", 0)
            data["needItems"] = comp.get("needItems", 0)
        return fmt(data, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)


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
async def syncthing_connections(params: ReadParams) -> str:
    """Current connection details for all devices."""
    try:
        client = get_instance(params.instance)
        connections = await client._get("/rest/system/connections")
        config = await client._get("/rest/config")
        devices_map = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }
        result = [
            format_connection(
                did, conn, devices_map.get(did, did[:8]), concise=params.concise,
            )
            for did, conn in connections.get("connections", {}).items()
        ]
        return fmt(result, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_device_stats",
    annotations={
        "title": "Device Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_device_stats(params: ReadParams) -> str:
    """Per-device statistics: last seen time and connection duration."""
    try:
        client = get_instance(params.instance)
        stats = await client._get("/rest/stats/device")
        config = await client._get("/rest/config")
        devices_map = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }
        result = []
        for did, stat in stats.items():
            entry: dict[str, Any] = {
                "device": devices_map.get(did, did[:8]),
                "lastSeen": stat.get("lastSeen", ""),
            }
            if not params.concise:
                entry["deviceID"] = did
                entry["lastConnectionDurationS"] = stat.get("lastConnectionDurationS", 0)
            result.append(entry)
        return fmt(result, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)
