"""Bearer token authentication middleware for Streamable HTTP transport."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validate ``Authorization: Bearer <token>`` on every request.

    Requests without a valid token receive a 401 response.  Health-check
    probes hitting ``/health`` are allowed through unauthenticated so that
    Docker / Traefik health checks work without token configuration.
    """

    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        # Allow unauthenticated health checks.
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != self.token:
            return JSONResponse(
                {"error": "Invalid or missing bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
