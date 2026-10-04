#!/usr/bin/env bash
# Set up wellpass-mcp: create a virtualenv, install the package, and prepare .env.
set -euo pipefail

cd "$(dirname "$0")/.."

PY_BIN="python3"
VENV=".venv"

echo "==> Setting up wellpass-mcp"

if command -v uv >/dev/null 2>&1; then
  echo "==> Using uv"
  uv venv "$VENV"
  uv pip install --python "$VENV/bin/python" -e ".[dev]"
else
  echo "==> uv not found; using $PY_BIN -m venv + pip"
  "$PY_BIN" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -e ".[dev]"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Created .env from .env.example (edit it to add your login for class search)"
else
  echo "==> .env already exists; leaving it as is"
fi

echo
echo "Done. Next:"
echo "  1. (optional) edit .env to add WELLPASS_EMAIL / WELLPASS_PASSWORD for class search"
echo "  2. run the server:   $VENV/bin/python -m wellpass_mcp.server"
echo "  3. or run the tests: $VENV/bin/python -m pytest -q"
echo
echo "To register with an MCP client, see the README (MCP setup)."
