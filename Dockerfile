FROM python:3.12-slim AS base

WORKDIR /app

# Install uv for fast dependency resolution.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project metadata first for layer caching.
COPY pyproject.toml ./
COPY src/ src/

# Install the package and all runtime dependencies.
RUN uv pip install --system --no-cache .

# Default to streamable-http transport in container.
ENV MCP_TRANSPORT=streamable-http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"]

ENTRYPOINT ["syncthing-mcp"]
