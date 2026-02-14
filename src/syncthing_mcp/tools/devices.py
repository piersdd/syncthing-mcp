"""Device completion and connection tools."""

import json

from syncthing_mcp.models import DeviceInput, EmptyInput
from syncthing_mcp.registry import (
    format_bytes,
    get_instance,
    handle_error_global,
)
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
async def syncthing_list_devices(params: EmptyInput) -> str:
    """List all configured devices with their names, connection status, and last seen time.

    Returns:
        str: JSON array of devices with deviceID, name, connected, paused, address, lastSeen.
    """
    try:
        client = get_instance(params.instance)
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
async def syncthing_device_completion(params: DeviceInput) -> str:
    """Get the aggregated sync completion for a specific remote device across all shared folders.

    Args:
        params: DeviceInput with device_id.

    Returns:
        str: JSON with overall completion %, globalBytes, needBytes for that device.
    """
    try:
        client = get_instance(params.instance)
        comp = await client._get(
            "/rest/db/completion", params={"device": params.device_id}
        )
        return json.dumps(
            {
                "deviceID": params.device_id,
                "instance": client.name,
                "completion": round(comp.get("completion", 0), 2),
                "globalBytes": comp.get("globalBytes", 0),
                "globalSize": format_bytes(comp.get("globalBytes", 0)),
                "needBytes": comp.get("needBytes", 0),
                "needSize": format_bytes(comp.get("needBytes", 0)),
                "needItems": comp.get("needItems", 0),
                "remoteState": comp.get("remoteState", "unknown"),
            },
            indent=2,
        )
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
async def syncthing_connections(params: EmptyInput) -> str:
    """Get current connection details for all devices.

    Returns:
        str: JSON with per-device connection info including address,
             bytes transferred, crypto, and connection type.
    """
    try:
        client = get_instance(params.instance)
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
        return handle_error_global(e)
