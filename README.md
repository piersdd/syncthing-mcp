# syncthing-mcp

An MCP (Model Context Protocol) server for [Syncthing](https://syncthing.net/) — the open-source continuous file synchronisation tool.

Built to give AI assistants (Claude, etc.) read and control access to Syncthing's REST API, with a focus on **replication awareness**: understanding which folders are fully replicated across devices so you can confidently reclaim local disk space.

## Why

Syncthing syncs folders across devices, but its web UI doesn't make it easy to answer a simple question: *"Which datasets on this machine are safely backed up elsewhere, and how much space would I recover by removing them locally?"*

This MCP server exposes that information as structured tool calls, so you can ask an AI assistant to audit your replication status and guide you through safe cleanup.

## Tools

| Tool | Description | Mutating |
|------|-------------|----------|
| `syncthing_system_status` | Device ID, name, uptime, version | No |
| `syncthing_list_folders` | All folders with paths, types, and shared device lists | No |
| `syncthing_list_devices` | All devices with connection status and last seen | No |
| `syncthing_folder_status` | Detailed status for a single folder (files, bytes, sync state) | No |
| `syncthing_folder_completion` | Per-device completion % for a folder | No |
| `syncthing_replication_report` | Analyses all folders, flags safe-to-remove, calculates reclaimable space | No |
| `syncthing_device_completion` | Aggregated completion for a device across all shared folders | No |
| `syncthing_connections` | Active connection details (addresses, crypto, throughput) | No |
| `syncthing_folder_errors` | Current sync errors for a folder | No |
| `syncthing_scan_folder` | Trigger an immediate rescan | Yes |
| `syncthing_pause_folder` | Pause a folder (prevents deletion propagation) | Yes |
| `syncthing_resume_folder` | Resume a paused folder | Yes |

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

### Configure Claude Desktop

Add to your Claude Desktop MCP config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "syncthing": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/syncthing-mcp",
        "run", "syncthing_mcp.py"
      ],
      "env": {
        "SYNCTHING_API_KEY": "your-api-key-here",
        "SYNCTHING_URL": "http://localhost:8384"
      }
    }
  }
}
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SYNCTHING_API_KEY` | Yes | — | API key from Syncthing settings |
| `SYNCTHING_URL` | No | `http://localhost:8384` | Base URL for the Syncthing REST API |

## Roadmap

This server is the foundation for a broader goal: a **Syncthing dataset dashboard** that provides ongoing visibility into synchronisation health across a fleet of devices.

Planned directions include:

- **Multi-instance support** — query multiple Syncthing nodes (e.g. NAS, servers, laptops) from a single MCP session, enabling cross-fleet replication views
- **Event stream integration** — subscribe to Syncthing's `/rest/events` endpoint for real-time sync status, conflict detection, and error alerting
- **Historical tracking** — persist folder size and completion data over time to surface trends (growth rate, sync frequency, stale folders)
- **Conflict management** — surface and resolve sync conflicts through tool calls rather than manual file inspection
- **Ignore pattern management** — read and update `.stignore` rules per folder
- **Folder lifecycle tools** — add/remove folders and device sharing relationships programmatically
- **Dashboard artifact** — a standalone HTML/React view that visualises replication topology, per-folder health, and reclaimable space across all nodes

## Performance Notes

- `syncthing_folder_status` and `syncthing_replication_report` call Syncthing's `/rest/db/status` endpoint, which the Syncthing docs describe as "an expensive call, increasing CPU and RAM usage on the device." Use judiciously on low-power hardware.
- The replication report makes one `/rest/db/completion` call per remote device per folder. On setups with many folders and devices, this can generate significant API traffic.

## Contributing

Issues and PRs welcome. This is an early-stage project — the API surface may change as the roadmap develops.

## License

MIT
