"""Folder status, completion, replication, operations, and file-level query tools."""

import json
from typing import Any

from syncthing_mcp.models import (
    BrowseFolderInput,
    FileInfoInput,
    FolderInput,
    FolderNeedInput,
    PauseFolderInput,
    EmptyInput,
)
from syncthing_mcp.registry import (
    format_bytes,
    get_instance,
    handle_error_global,
)
from syncthing_mcp.server import mcp


# =====================================================================
#  Folder Status & Replication
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
        client = get_instance(params.instance)
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
                "globalSize": format_bytes(status.get("globalBytes", 0)),
                "localFiles": status.get("localFiles"),
                "localBytes": status.get("localBytes"),
                "localSize": format_bytes(status.get("localBytes", 0)),
                "needFiles": status.get("needFiles"),
                "needBytes": status.get("needBytes"),
                "needSize": format_bytes(status.get("needBytes", 0)),
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
                        "globalSize": format_bytes(comp.get("globalBytes", 0)),
                        "needBytes": comp.get("needBytes", 0),
                        "needSize": format_bytes(comp.get("needBytes", 0)),
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
                    "localSize": format_bytes(local_bytes),
                    "globalBytes": global_bytes,
                    "globalSize": format_bytes(global_bytes),
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
                    "totalReclaimableSize": format_bytes(total_reclaimable),
                },
                "folders": report,
            },
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)


# =====================================================================
#  Folder Operations
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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


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
        client = get_instance(params.instance)
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
        return handle_error_global(e)


# =====================================================================
#  New: File-level queries
# =====================================================================


@mcp.tool(
    name="syncthing_browse_folder",
    annotations={
        "title": "Browse Folder Contents",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_browse_folder(params: BrowseFolderInput) -> str:
    """Browse the contents of a folder at a given path prefix.

    Returns a directory-style listing of files and subdirectories known to
    Syncthing's database — useful for inspecting what is being synced without
    direct filesystem access.

    Args:
        params: BrowseFolderInput with folder_id, optional prefix and levels.

    Returns:
        str: JSON with the folder contents at the requested path.
    """
    try:
        client = get_instance(params.instance)
        query: dict[str, str] = {"folder": params.folder_id}
        if params.prefix:
            query["prefix"] = params.prefix
        if params.levels is not None:
            query["levels"] = str(params.levels)
        result = await client._get("/rest/db/browse", params=query)
        return json.dumps(
            {
                "folder": params.folder_id,
                "instance": client.name,
                "prefix": params.prefix or "",
                "entries": result,
            },
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_file_info",
    annotations={
        "title": "File Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_file_info(params: FileInfoInput) -> str:
    """Get detailed information about a specific file within a folder.

    Returns version vectors, availability on devices, modification time,
    size, and whether the file is locally present.  Useful for diagnosing
    sync conflicts or understanding file state across the cluster.

    Args:
        params: FileInfoInput with folder_id and file_path.

    Returns:
        str: JSON with file metadata including global and local info.
    """
    try:
        client = get_instance(params.instance)
        result = await client._get(
            "/rest/db/file",
            params={"folder": params.folder_id, "file": params.file_path},
        )
        # Enrich with human-readable sizes
        for key in ("global", "local"):
            entry = result.get(key)
            if isinstance(entry, dict) and "size" in entry:
                entry["sizeFormatted"] = format_bytes(entry["size"])
        return json.dumps(
            {
                "folder": params.folder_id,
                "file": params.file_path,
                "instance": client.name,
                "availability": result.get("availability"),
                "global": result.get("global"),
                "local": result.get("local"),
            },
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_folder_need",
    annotations={
        "title": "Folder Need (Out-of-Sync Files)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_folder_need(params: FolderNeedInput) -> str:
    """List files that the folder still needs — items that are out of sync locally.

    Supports pagination for large result sets.

    Args:
        params: FolderNeedInput with folder_id, page, per_page.

    Returns:
        str: JSON with lists of files needed (progress, queued, rest) and a total page count.
    """
    try:
        client = get_instance(params.instance)
        result = await client._get(
            "/rest/db/need",
            params={
                "folder": params.folder_id,
                "page": str(params.page),
                "perpage": str(params.per_page),
            },
        )
        return json.dumps(
            {
                "folder": params.folder_id,
                "instance": client.name,
                "page": result.get("page", params.page),
                "perpage": result.get("perpage", params.per_page),
                "progress": result.get("progress", []),
                "queued": result.get("queued", []),
                "rest": result.get("rest", []),
            },
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)


# =====================================================================
#  New: Conflict resolution
# =====================================================================


@mcp.tool(
    name="syncthing_override_folder",
    annotations={
        "title": "Override Remote Changes (Send-Only)",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_override_folder(params: FolderInput) -> str:
    """Override remote changes on a send-only folder, making local state authoritative.

    Use this when a send-only folder shows 'out of sync' items that you want
    to push to remote devices.  Only meaningful for folders configured as
    'sendonly'.

    Args:
        params: FolderInput with folder_id.

    Returns:
        str: Confirmation that the override was requested.
    """
    try:
        client = get_instance(params.instance)
        await client._post("/rest/db/override", params={"folder": params.folder_id})
        return json.dumps(
            {
                "status": "override_requested",
                "folder": params.folder_id,
                "instance": client.name,
                "message": (
                    f"Override requested for folder '{params.folder_id}'. "
                    "Local state will be pushed to remote devices."
                ),
            },
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_revert_folder",
    annotations={
        "title": "Revert Local Changes (Receive-Only)",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_revert_folder(params: FolderInput) -> str:
    """Revert local changes on a receive-only folder, pulling the remote state.

    Use this when a receive-only folder has local modifications that should be
    discarded in favour of the remote version.

    Args:
        params: FolderInput with folder_id.

    Returns:
        str: Confirmation that the revert was requested.
    """
    try:
        client = get_instance(params.instance)
        await client._post("/rest/db/revert", params={"folder": params.folder_id})
        return json.dumps(
            {
                "status": "revert_requested",
                "folder": params.folder_id,
                "instance": client.name,
                "message": (
                    f"Revert requested for folder '{params.folder_id}'. "
                    "Local changes will be replaced by the remote state."
                ),
            },
            indent=2,
        )
    except Exception as e:
        return handle_error_global(e)
