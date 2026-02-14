"""Tools for instance management and listing folders (config-level)."""

import json
from typing import Any

from syncthing_mcp.models import EmptyInput
from syncthing_mcp.registry import (
    format_bytes,
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
async def syncthing_list_instances(params: EmptyInput) -> str:
    """List all configured Syncthing instances and probe their availability.

    Returns:
        str: JSON array with instance name, URL, availability, and device ID.
    """
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
        client = get_instance(params.instance)
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
        return handle_error_global(e)
