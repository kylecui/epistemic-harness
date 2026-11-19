#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${REPO_ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
export UPSTREAM_OPENAI_URL="${UPSTREAM_OPENAI_URL:-https://api.openai.com/v1}"
export UPSTREAM_ANTHROPIC_URL="${UPSTREAM_ANTHROPIC_URL:-https://api.anthropic.com}"
HOST="${HARNESS_PROXY_HOST:-127.0.0.1}"
PORT="${HARNESS_PROXY_PORT:-8787}"
echo "Starting Epistemic Harness Proxy Gateway on http://${HOST}:${PORT} ..."
exec "$PY" -m uvicorn proxy_gateway.app:app --host "$HOST" --port "$PORT"
