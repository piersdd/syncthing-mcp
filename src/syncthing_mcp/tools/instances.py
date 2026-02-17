"""Tools for instance management and listing folders (config-level)."""

from typing import Any

from syncthing_mcp.formatters import fmt, format_folder
from syncthing_mcp.models import ReadParams
from syncthing_mcp.registry import (
    get_all_instances,
    get_instance,
    handle_error_global,
)
from syncthing_mcp.server import mcp


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
async def syncthing_list_instances(params: ReadParams) -> str:
    """List all configured Syncthing instances and probe their availability."""
    results = []
    for name, client in get_all_instances().items():
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
            entry.update({
                "available": True,
                "deviceName": my_name,
                "version": version.get("version"),
                "folders": len(config.get("folders", [])),
                "devices": len(config.get("devices", [])),
            })
            if not params.concise:
                entry["myID"] = my_id
        except Exception as exc:
            entry.update({"available": False, "error": str(exc)})
        results.append(entry)
    return fmt(results, concise=params.concise)


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
async def syncthing_list_folders(params: ReadParams) -> str:
    """All configured folders with labels, types, and device counts."""
    try:
        client = get_instance(params.instance)
        config = await client._get("/rest/config")
        folders = config.get("folders", [])
        if params.concise:
            result = [format_folder(f, concise=True) for f in folders]
        else:
            devices_map = {
                d["deviceID"]: d.get("name", d["deviceID"][:8])
                for d in config.get("devices", [])
            }
            result = []
            for f in folders:
                shared = [
                    {"deviceID": d.get("deviceID", ""), "name": devices_map.get(d.get("deviceID", ""), "")}
                    for d in f.get("devices", [])
                ]
                result.append({
                    "id": f["id"],
                    "label": f.get("label", f["id"]),
                    "path": f.get("path", ""),
                    "type": f.get("type", "sendreceive"),
                    "paused": f.get("paused", False),
                    "sharedWith": shared,
                })
        return fmt(result, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)
