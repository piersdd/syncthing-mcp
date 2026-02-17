"""Tests for folder tools (status, completion, replication, operations, new tools)."""

import json

import pytest
import respx

from syncthing_mcp.models import (
    BrowseFolderInput,
    EmptyInput,
    FileInfoInput,
    FolderInput,
    FolderNeedInput,
    PauseFolderInput,
)
from syncthing_mcp.registry import reload_instances
from tests.conftest import (
    BASE_URL,
    DEVICE_ID_LOCAL,
    DEVICE_ID_REMOTE,
    FOLDER_ID,
    make_completion,
    make_config,
    make_connections,
    make_db_status,
    make_stats_folder,
    make_system_status,
)


@pytest.fixture(autouse=True)
def _setup(single_instance_env):
    reload_instances()
    yield
    reload_instances()


class TestFolderStatus:
    async def test_returns_status(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_status

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        result = json.loads(await syncthing_folder_status(FolderInput(folder_id=FOLDER_ID)))
        assert result["folder"] == FOLDER_ID
        assert result["state"] == "idle"
        assert result["globalSize"] is not None


class TestFolderCompletion:
    async def test_fully_replicated(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_completion

        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))
        result = json.loads(await syncthing_folder_completion(FolderInput(folder_id=FOLDER_ID)))
        assert result["fullyReplicated"] == 1
        assert result["devices"][0]["completion"] == 100.0

    async def test_partially_replicated(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_completion

        mock_api.get("/rest/db/completion").respond(json=make_completion(75.0, "unknown"))
        result = json.loads(await syncthing_folder_completion(FolderInput(folder_id=FOLDER_ID)))
        assert result["fullyReplicated"] == 0

    async def test_folder_not_found(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_completion

        result = json.loads(await syncthing_folder_completion(FolderInput(folder_id="nonexistent")))
        assert "error" in result


class TestReplicationReport:
    async def test_safe_to_remove(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_replication_report

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))
        result = json.loads(await syncthing_replication_report(EmptyInput()))
        assert result["summary"]["safe"] == 1
        assert result["folders"][0]["safe"] is True

    async def test_not_safe_when_incomplete(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_replication_report

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        mock_api.get("/rest/db/completion").respond(json=make_completion(50.0))
        result = json.loads(await syncthing_replication_report(EmptyInput()))
        assert result["summary"]["safe"] == 0


class TestPauseFolder:
    async def test_pause(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_pause_folder

        mock_api.get(f"/rest/config/folders/{FOLDER_ID}").respond(
            json={"id": FOLDER_ID, "paused": False}
        )
        mock_api.patch(f"/rest/config/folders/{FOLDER_ID}").respond(
            json={"id": FOLDER_ID, "paused": True},
            headers={"content-type": "application/json"},
        )
        result = json.loads(await syncthing_pause_folder(PauseFolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "paused"


class TestResumeFolder:
    async def test_resume(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_resume_folder

        mock_api.get(f"/rest/config/folders/{FOLDER_ID}").respond(
            json={"id": FOLDER_ID, "type": "sendreceive", "paused": True}
        )
        mock_api.patch(f"/rest/config/folders/{FOLDER_ID}").respond(
            json={"id": FOLDER_ID, "paused": False},
            headers={"content-type": "application/json"},
        )
        result = json.loads(await syncthing_resume_folder(PauseFolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "resumed"
        assert result["type"] == "sendreceive"


class TestScanFolder:
    async def test_scan(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_scan_folder

        mock_api.post("/rest/db/scan").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_scan_folder(FolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "scan_requested"


class TestFolderErrors:
    async def test_no_errors(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_errors

        mock_api.get("/rest/folder/errors").respond(json={"errors": None, "page": 1})
        result = json.loads(await syncthing_folder_errors(FolderInput(folder_id=FOLDER_ID)))
        assert result["count"] == 0


class TestBrowseFolder:
    async def test_browse_root(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_browse_folder

        mock_api.get("/rest/db/browse").respond(json=[
            {"name": "docs", "type": "directory"},
            {"name": "readme.txt", "type": "file"},
        ])
        result = json.loads(await syncthing_browse_folder(BrowseFolderInput(folder_id=FOLDER_ID)))
        assert result["folder"] == FOLDER_ID
        assert len(result["entries"]) == 2

    async def test_browse_with_prefix(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_browse_folder

        route = mock_api.get("/rest/db/browse").respond(json=[])
        result = json.loads(await syncthing_browse_folder(
            BrowseFolderInput(folder_id=FOLDER_ID, prefix="docs", levels=2)
        ))
        assert result["prefix"] == "docs"


class TestFileInfo:
    async def test_file_info(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_file_info

        mock_api.get("/rest/db/file").respond(json={
            "availability": [{"id": DEVICE_ID_REMOTE}],
            "global": {"name": "test.txt", "size": 1024, "modified": "2025-01-01T00:00:00Z"},
            "local": {"name": "test.txt", "size": 1024},
        })
        result = json.loads(await syncthing_file_info(
            FileInfoInput(folder_id=FOLDER_ID, file_path="test.txt")
        ))
        assert result["file"] == "test.txt"
        # Concise mode returns globalSize at top level
        assert result["globalSize"] == "1.0 KB"


class TestFolderNeed:
    async def test_need_empty(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_need

        mock_api.get("/rest/db/need").respond(json={
            "page": 1, "perpage": 50,
            "progress": [], "queued": [], "rest": [],
        })
        result = json.loads(await syncthing_folder_need(FolderNeedInput(folder_id=FOLDER_ID)))
        assert result["progress"] == []
        assert result["queued"] == []


class TestOverrideFolder:
    async def test_override(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_override_folder

        mock_api.post("/rest/db/override").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_override_folder(FolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "override_requested"


class TestRevertFolder:
    async def test_revert(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_revert_folder

        mock_api.post("/rest/db/revert").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_revert_folder(FolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "revert_requested"
