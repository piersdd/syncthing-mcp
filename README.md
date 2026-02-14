# syncthing-mcp

An MCP (Model Context Protocol) server for [Syncthing](https://syncthing.net/) — the open-source continuous file synchronisation tool.

Built to give AI assistants (Claude, etc.) read and control access to Syncthing's REST API, with a focus on **replication awareness**: understanding which folders are fully replicated across devices so you can confidently reclaim local disk space.

## Why

Syncthing syncs folders across devices, but its web UI doesn't make it easy to answer a simple question: *"Which datasets on this machine are safely backed up elsewhere, and how much space would I recover by removing them locally?"*

This MCP server exposes that information as structured tool calls, so you can ask an AI assistant to audit your replication status and guide you through safe cleanup.

## Tools (36 total)

### Instance Management

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_list_instances` | List all configured instances, probe availability | No |

### System Status & Monitoring

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_system_status` | Device ID, name, uptime, version | No |
| `syncthing_list_folders` | All folders with paths, types, and shared device lists | No |
| `syncthing_list_devices` | All devices with connection status and last seen | No |
| `syncthing_connections` | Active connection details (addresses, crypto, throughput) | No |
| `syncthing_system_errors` | Recent system errors and warnings | No |
| `syncthing_clear_errors` | Clear the system error log | Yes |
| `syncthing_system_log` | Recent log entries with timestamps and levels | No |
| `syncthing_recent_changes` | Recent file change events (local + remote) | No |
| `syncthing_health_summary` | Single-call health overview: status, alerts, folder/device/pending counts | No |
| `syncthing_check_upgrade` | Check if a newer version of Syncthing is available | No |

### Folder Status & Replication

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_folder_status` | Detailed status for a single folder (files, bytes, sync state) | No |
| `syncthing_folder_completion` | Per-device completion % for a folder | No |
| `syncthing_replication_report` | Analyses all folders, flags safe-to-remove, calculates reclaimable space | No |
| `syncthing_folder_errors` | Current sync errors for a folder | No |

### Device Status

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_device_completion` | Aggregated completion for a device across all shared folders | No |

### Folder Operations

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_scan_folder` | Trigger an immediate rescan | Yes |
| `syncthing_pause_folder` | Pause a folder (prevents deletion propagation) | Yes |
| `syncthing_resume_folder` | Resume a paused folder | Yes |

### File-Level Queries

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_browse_folder` | Browse folder contents at a path prefix (directory listing from Syncthing's DB) | No |
| `syncthing_file_info` | Detailed info about a specific file (versions, availability, conflicts) | No |
| `syncthing_folder_need` | List out-of-sync files a folder still needs (with pagination) | No |

### Conflict Resolution

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_override_folder` | Override remote changes on a send-only folder (make local authoritative) | Yes |
| `syncthing_revert_folder` | Revert local changes on a receive-only folder (pull remote state) | Yes |

### Config Mutation: Pending Devices & Folders

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_pending_devices` | List pending device connection requests | No |
| `syncthing_pending_folders` | List pending folder share offers | No |
| `syncthing_accept_device` | Accept a pending device (adds to config with defaults) | Yes |
| `syncthing_reject_device` | Dismiss a pending device request | Yes |
| `syncthing_accept_folder` | Accept a pending folder offer (uses folder defaults template) | Yes |
| `syncthing_reject_folder` | Dismiss a pending folder offer | Yes |

### Config Mutation: Restart & Ignore Patterns

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_restart_required` | Check if config changes require a restart | No |
| `syncthing_restart` | Restart the Syncthing service | Yes |
| `syncthing_get_ignores` | Get .stignore patterns for a folder | No |
| `syncthing_set_ignores` | Set .stignore patterns for a folder (replaces all) | Yes |
| `syncthing_get_default_ignores` | Get default ignore patterns for new folders | No |
| `syncthing_set_default_ignores` | Set default ignore patterns for new folders | Yes |

## Project Structure

```
syncthing-mcp/
├── src/syncthing_mcp/
│   ├── __init__.py          # Package version
│   ├── __main__.py          # Entry point
│   ├── client.py            # SyncthingClient (HTTP methods + error handling)
│   ├── models.py            # Pydantic input models
│   ├── registry.py          # Multi-instance registry from env vars
│   ├── server.py            # FastMCP server + lifespan
│   └── tools/
│       ├── system.py        # System status, health, errors, log, restart, upgrade
│       ├── folders.py       # Folder status, completion, replication, operations, file queries
│       ├── devices.py       # Device completion, connections
│       ├── config.py        # Pending accept/reject, ignore patterns
│       └── instances.py     # Instance listing, folder listing
├── tests/                   # 96 tests with respx HTTP mocking
├── pyproject.toml
└── README.md
```

## Multi-Instance Support

Connect to multiple Syncthing nodes simultaneously by setting the `SYNCTHING_INSTANCES` environment variable with a JSON object:

```json
{
  "mini":  {"url": "http://mini.local:8384",  "api_key": "abc123"},
  "tn-sb": {"url": "http://tn-sb.local:8384", "api_key": "def456"},
  "tn-mr2": {"url": "http://tn-mr2.local:8384", "api_key": "ghi789"}
}
```

Every tool accepts an optional `instance` parameter to target a specific node. When only one instance is configured, the parameter can be omitted.

### Claude Desktop config (multi-instance)

```json
{
  "mcpServers": {
    "syncthing": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/syncthing-mcp",
        "run", "python", "-m", "syncthing_mcp"
      ],
      "env": {
        "SYNCTHING_INSTANCES": "{\"mini\":{\"url\":\"http://mini.local:8384\",\"api_key\":\"abc123\"},\"tn-sb\":{\"url\":\"http://tn-sb.local:8384\",\"api_key\":\"def456\"}}"
      }
    }
  }
}
```

## Safe Removal Workflow

1. Run `syncthing_replication_report` — review which folders show `safeToRemove: true`
2. Confirm the fully-replicated remote device(s) are the ones you expect
3. `syncthing_pause_folder` — stops Syncthing from propagating local changes
4. Delete the local data outside of Syncthing
5. Optionally remove the folder from this device's config via the Syncthing web UI

> **Important:** Always pause before deleting. In a `sendreceive` folder, deleting files without pausing will propagate the deletion to all connected devices.

The `safeToRemove` flag requires: at least one remote device at 100% completion with `remoteState: valid`, the folder in `idle` state, and the folder not paused. This is deliberately conservative.

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A running Syncthing instance with API access

### Install

```bash
git clone https://github.com/piersdd/syncthing-mcp.git
cd syncthing-mcp
uv sync
```

### Get your Syncthing API key

Open the Syncthing web UI → Actions → Settings → API Key.

Alternatively, find it in your Syncthing config file under `<gui><apikey>`.

### Configure Claude Desktop (single instance)

Add to your Claude Desktop MCP config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "syncthing": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/syncthing-mcp",
        "run", "python", "-m", "syncthing_mcp"
      ],
      "env": {
        "SYNCTHING_API_KEY": "your-api-key-here",
        "SYNCTHING_URL": "http://localhost:8384"
      }
    }
  }
}
```

### Running Tests

```bash
uv sync
uv run pytest -v
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SYNCTHING_API_KEY` | Yes* | — | API key (single-instance mode) |
| `SYNCTHING_URL` | No | `http://localhost:8384` | Base URL (single-instance mode) |
| `SYNCTHING_INSTANCES` | No | — | JSON object for multi-instance mode (overrides the above) |

\* Required unless `SYNCTHING_INSTANCES` is set.

## Performance Notes

- `syncthing_folder_status` and `syncthing_replication_report` call Syncthing's `/rest/db/status` endpoint, which the Syncthing docs describe as "an expensive call, increasing CPU and RAM usage on the device." Use judiciously on low-power hardware.
- The replication report makes one `/rest/db/completion` call per remote device per folder. On setups with many folders and devices, this can generate significant API traffic.
- `syncthing_health_summary` calls `/rest/db/status` for each folder — equivalent cost to the replication report.

## Contributing

Issues and PRs welcome.

## License

MIT
