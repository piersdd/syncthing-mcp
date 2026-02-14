#!/usr/bin/env bash
set -euo pipefail

SERVER_NAME="syncthing-mcp"
DEST="$HOME/.local/share/mcp-servers/$SERVER_NAME"

# Clean deploy — wipe previous, copy fresh
mkdir -p "$DEST"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  . "$DEST/"

# Install/update deps in the runtime location
cd "$DEST"
uv sync --quiet

echo "✅ Deployed $SERVER_NAME to $DEST"
echo "   Restart Claude Desktop to pick up changes."