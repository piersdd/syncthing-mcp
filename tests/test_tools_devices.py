"""Tests for device tools (list, completion, connections)."""

import json

import pytest

from syncthing_mcp.models import DeviceInput, EmptyInput
from syncthing_mcp.registry import reload_instances
from tests.conftest import (
    BASE_URL,
    DEVICE_ID_LOCAL,
    DEVICE_ID_REMOTE,
    make_completion,
)


@pytest.fixture(autouse=True)
def _setup(single_instance_env):
    reload_instances()
    yield
    reload_instances()


class TestListDevices:
    async def test_returns_devices(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_list_devices

        result = json.loads(await syncthing_list_devices(EmptyInput()))
        assert len(result) == 2
        names = {d["name"] for d in result}
        assert "local-dev" in names
        assert "remote-dev" in names


class TestDeviceCompletion:
    async def test_fully_synced(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_device_completion

        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))
        result = json.loads(await syncthing_device_completion(
            DeviceInput(device_id=DEVICE_ID_REMOTE)
        ))
        assert result["completion"] == 100.0
        assert result["needBytes"] == 0


class TestConnections:
    async def test_returns_connections(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_connections

        result = json.loads(await syncthing_connections(EmptyInput()))
        assert len(result) == 2
        assert any(c["connected"] for c in result)
