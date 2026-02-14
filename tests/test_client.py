"""Tests for SyncthingClient HTTP methods and error handling."""

import httpx
import pytest
import respx
from httpx import Response

from syncthing_mcp.client import SyncthingClient

BASE_URL = "http://localhost:8384"
API_KEY = "test-key"


@pytest.fixture
def client():
    return SyncthingClient("test", BASE_URL, API_KEY)


class TestGet:
    async def test_get_json(self, client):
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/rest/system/status").respond(json={"myID": "abc123"})
            result = await client._get("/rest/system/status")
            assert result["myID"] == "abc123"

    async def test_get_with_params(self, client):
        with respx.mock(base_url=BASE_URL) as router:
            route = router.get("/rest/db/status").respond(json={"state": "idle"})
            result = await client._get("/rest/db/status", params={"folder": "f1"})
            assert result["state"] == "idle"
            assert route.calls[0].request.url.params["folder"] == "f1"

    async def test_get_401(self, client):
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/rest/system/status").respond(status_code=401)
            with pytest.raises(httpx.HTTPStatusError):
                await client._get("/rest/system/status")


class TestPost:
    async def test_post_json_response(self, client):
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/db/scan").respond(json={"ok": True}, headers={"content-type": "application/json"})
            result = await client._post("/rest/db/scan", params={"folder": "f1"})
            assert result == {"ok": True}

    async def test_post_empty_response(self, client):
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/system/restart").respond(status_code=200, content=b"")
            result = await client._post("/rest/system/restart")
            assert result == {"status": "ok"}


class TestPatch:
    async def test_patch(self, client):
        with respx.mock(base_url=BASE_URL) as router:
            router.patch("/rest/config/folders/f1").respond(json={"id": "f1"}, headers={"content-type": "application/json"})
            result = await client._patch("/rest/config/folders/f1", body={"paused": True})
            assert result["id"] == "f1"


class TestPut:
    async def test_put(self, client):
        with respx.mock(base_url=BASE_URL) as router:
            router.put("/rest/config/defaults/ignores").respond(json={"lines": []}, headers={"content-type": "application/json"})
            result = await client._put("/rest/config/defaults/ignores", body={"lines": ["*.tmp"]})
            assert result == {"lines": []}


class TestDelete:
    async def test_delete(self, client):
        with respx.mock(base_url=BASE_URL) as router:
            router.delete("/rest/cluster/pending/devices").respond(status_code=200, content=b"")
            result = await client._delete("/rest/cluster/pending/devices", params={"device": "ABCDEF"})
            assert result == {"status": "ok"}


class TestHandleError:
    def test_401(self, client):
        req = httpx.Request("GET", f"{BASE_URL}/rest/test")
        resp = httpx.Response(401, request=req)
        err = httpx.HTTPStatusError("401", request=req, response=resp)
        msg = client.handle_error(err)
        assert "401" in msg
        assert "Unauthorized" in msg

    def test_403(self, client):
        req = httpx.Request("GET", f"{BASE_URL}/rest/test")
        resp = httpx.Response(403, request=req)
        err = httpx.HTTPStatusError("403", request=req, response=resp)
        msg = client.handle_error(err)
        assert "403" in msg
        assert "Forbidden" in msg

    def test_404(self, client):
        req = httpx.Request("GET", f"{BASE_URL}/rest/test")
        resp = httpx.Response(404, request=req, text="not found")
        err = httpx.HTTPStatusError("404", request=req, response=resp)
        msg = client.handle_error(err)
        assert "404" in msg

    def test_connect_error(self, client):
        err = httpx.ConnectError("Connection refused")
        msg = client.handle_error(err)
        assert "Cannot connect" in msg
        assert BASE_URL in msg

    def test_timeout(self, client):
        err = httpx.ReadTimeout("timed out")
        msg = client.handle_error(err)
        assert "timed out" in msg.lower() or "Request timed out" in msg

    def test_generic_error(self, client):
        err = RuntimeError("something broke")
        msg = client.handle_error(err)
        assert "RuntimeError" in msg
        assert "something broke" in msg

    def test_default_instance_no_prefix(self):
        c = SyncthingClient("default", BASE_URL, API_KEY)
        err = RuntimeError("test")
        msg = c.handle_error(err)
        assert not msg.startswith("[default]")

    def test_named_instance_has_prefix(self):
        c = SyncthingClient("mynas", BASE_URL, API_KEY)
        err = RuntimeError("test")
        msg = c.handle_error(err)
        assert msg.startswith("[mynas]")
