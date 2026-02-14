"""HTTP client for a single Syncthing instance."""

from typing import Any

import httpx


class SyncthingClient:
    """HTTP client for a single Syncthing instance."""

    def __init__(self, name: str, url: str, api_key: str) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any:
        """Authenticated GET against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.url}{path}",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, params: dict | None = None, body: Any = None) -> Any:
        """Authenticated POST against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.url}{path}",
                headers=self._headers(),
                params=params,
                json=body,
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json") and resp.content:
                return resp.json()
            return {"status": "ok"}

    async def _patch(self, path: str, body: Any = None) -> Any:
        """Authenticated PATCH against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{self.url}{path}",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json") and resp.content:
                return resp.json()
            return {"status": "ok"}

    async def _put(self, path: str, body: Any = None) -> Any:
        """Authenticated PUT against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"{self.url}{path}",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json") and resp.content:
                return resp.json()
            return {"status": "ok"}

    async def _delete(self, path: str, params: dict | None = None) -> Any:
        """Authenticated DELETE against this instance."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{self.url}{path}",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json") and resp.content:
                return resp.json()
            return {"status": "ok"}

    def handle_error(self, e: Exception) -> str:
        """Consistent error formatting referencing this instance."""
        prefix = f"[{self.name}] " if self.name != "default" else ""
        if isinstance(e, httpx.HTTPStatusError):
            status = e.response.status_code
            if status == 401:
                return f"{prefix}Error 401: Unauthorized. Check API key for instance '{self.name}'."
            if status == 403:
                return f"{prefix}Error 403: Forbidden. API key may lack permissions."
            if status == 404:
                return f"{prefix}Error 404: Not found. Check the folder/device ID. Detail: {e.response.text}"
            return f"{prefix}Error {status}: {e.response.text}"
        if isinstance(e, httpx.ConnectError):
            return f"{prefix}Error: Cannot connect to Syncthing at {self.url}. Is it running?"
        if isinstance(e, httpx.TimeoutException):
            return f"{prefix}Error: Request timed out. Syncthing may be busy or unreachable."
        return f"{prefix}Error: {type(e).__name__}: {e}"
