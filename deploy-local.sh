#!/usr/bin/env bash
# deploy-local.sh
DEST="$HOME/.local/share/mcp-servers/syncthing-mcp"
mkdir -p "$DEST"
rsync -a --delete --exclude '.git' --exclude '.venv' --exclude '__pycache__' . "$DEST/"
cd "$DEST" && uv sync --quiet