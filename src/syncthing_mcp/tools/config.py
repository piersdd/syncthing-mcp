"""Config mutation tools: pending devices/folders, ignores, accept/reject."""

import json

from syncthing_mcp.models import (
    AcceptDeviceInput,
    AcceptFolderInput,
    DeviceInput,
    EmptyInput,
    FolderInput,
    RejectFolderInput,
    SetDefaultIgnoresInput,
    SetIgnoresInput,
)
from syncthing_mcp.registry import get_instance, handle_error_global
from syncthing_mcp.server import mcp


# =====================================================================
#  Pending Devices & Folders
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
        client = get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/devices")
        return json.dumps(
            {"instance": client.name, "pendingDevices": pending},
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)


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
        client = get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/folders")
        return json.dumps(
            {"instance": client.name, "pendingFolders": pending},
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)


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
        client = get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/devices")
        pending_info = pending.get(params.device_id, {})
        name = params.name
        if not name:
            name = pending_info.get("name", params.device_id[:8])
        defaults = await client._get("/rest/config/defaults/device")
        new_device = defaults.copy()
        new_device["deviceID"] = params.device_id
        new_device["name"] = name
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/folders")
        folder_pending = pending.get(params.folder_id, {})
        if not folder_pending:
            return json.dumps(
                {"error": f"Folder '{params.folder_id}' not found in pending offers."}
            )
        offering_devices = list(folder_pending.get("offeredBy", {}).keys())
        first_offer = next(iter(folder_pending.get("offeredBy", {}).values()), {})
        label = first_offer.get("label", params.folder_id)
        status = await client._get("/rest/system/status")
        my_id = status.get("myID", "")
        defaults = await client._get("/rest/config/defaults/folder")
        new_folder = defaults.copy()
        new_folder["id"] = params.folder_id
        new_folder["label"] = label
        if params.path:
            new_folder["path"] = params.path
        device_list = [{"deviceID": my_id}]
        for did in offering_devices:
            device_list.append({"deviceID": did})
        new_folder["devices"] = device_list
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


# =====================================================================
#  Ignore Patterns
# =====================================================================


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
        result = await client._get("/rest/config/defaults/ignores")
        return json.dumps(
            {
                "instance": client.name,
                "lines": result.get("lines", []) or [],
            },
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)
