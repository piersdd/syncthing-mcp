# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2025-02-16

### Added
- Streamable HTTP transport mode (`MCP_TRANSPORT=streamable-http`)
- Bearer token authentication middleware for HTTP transport
- Docker and Docker Compose deployment with Traefik integration
- Health check endpoint at `/health`
- Package refactor into `src/syncthing_mcp/` layout with dedicated tool modules
- 6 new tools: `syncthing_health_summary`, `syncthing_check_upgrade`, `syncthing_browse_folder`, `syncthing_file_info`, `syncthing_folder_need`, `syncthing_recent_changes`
- 96 tests with `respx` HTTP mocking
- Multi-instance support via `SYNCTHING_INSTANCES` environment variable
- Config mutation tools: accept/reject pending devices and folders, ignore patterns
- Expanded monitoring: system errors, log access, restart control

## [0.1.0] - 2025-02-16

### Added
- Initial release
- Core Syncthing REST API wrapper as MCP server
- Folder status, completion, and replication report tools
- Device status and connection tools
- System status and error tools
- stdio transport for Claude Desktop integration

[Unreleased]: https://github.com/piersdd/syncthing-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/piersdd/syncthing-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/piersdd/syncthing-mcp/releases/tag/v0.1.0
