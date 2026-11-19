#!/usr/bin/env bash
# Epistemic Harness — Interactive API Key Manager & One-Click Launcher (macOS / Linux)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
VENV_PY="${REPO_ROOT}/.venv/bin/python"
[[ -x "$VENV_PY" ]] || VENV_PY="$(command -v python3)"
PORT="${HARNESS_PROXY_PORT:-8787}"
CONFIGURE=0
PROXY_ONLY=0
LOGIN=0

for arg in "$@"; do
  case "$arg" in
    --configure|-c) CONFIGURE=1 ;;
    --proxy-only)   PROXY_ONLY=1 ;;
    --login)        LOGIN=1 ;;
    --global|-g)    GLOBAL=1 ;;
  esac
done

copilot_login() {
  # Device-code login (same flow Pi uses) -> .secrets/github-copilot.json
  echo ""
  echo "=== GitHub Copilot device login ==="
  ( cd "$REPO_ROOT" && HARNESS_SECRETS_DIR="$REPO_ROOT/.secrets" "$VENV_PY" -m proxy_gateway.provider_auth login )
}

if [[ "$LOGIN" -eq 1 ]]; then
  copilot_login
  exit $?
fi

touch "${REPO_ROOT}/.gitignore"
grep -qxF ".env" "${REPO_ROOT}/.gitignore" || printf "\n.env\ntraces/\npromotions/\n.venv/\n" >> "${REPO_ROOT}/.gitignore"

if [[ "$CONFIGURE" -eq 1 || ! -f "$ENV_FILE" ]]; then
  "$VENV_PY" - "$ENV_FILE" << 'INNER_PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
kv = {}
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip().strip('"').strip("'")

providers = [
    ("ZHIPU_API_KEY", "ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4", "[Primary 1] Zhipu V2 Max"),
    ("KIMI_API_KEY", "KIMI_BASE_URL", "https://api.kimi.com/coding/v1", "[Primary 2] Kimi Allegretto"),
    ("OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL", "https://opencode.ai/inference/go/v1", "[Primary 3] OpenCode Go"),
    ("GITHUB_COPILOT_TOKEN", "GITHUB_COPILOT_BASE_URL", "https://api.githubcopilot.com", "[Last Option 1] GitHub Copilot Pro+"),
    ("GEMINI_API_KEY", "GOOGLE_AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai", "[Last Option 2] Google AI Pro"),
]
print("=== Epistemic Harness API Key Setup (press Enter to keep/skip) ===")
for key, ukey, durl, label in providers:
    if key == "GITHUB_COPILOT_TOKEN":
        print(f"{label} | device-code login (no static key). Run: ./start_harness.sh --login")
        kv.setdefault(ukey, durl)
        continue
    cur = kv.get(key, "")
    masked = f"{cur[:4]}****{cur[-4:]}" if len(cur) > 8 else ("****" if cur else "(not set)")
    val = input(f"{label} | {key} [{masked}]: ").strip()
    if val:
        kv[key] = val
    kv.setdefault(ukey, durl)
kv.setdefault("KIMI_CODING_BASE_URL", "https://api.kimi.com/coding/v1")
kv.setdefault("HARNESS_THINKING_LANG", "en_with_native_terms")
lines = ["# Auto-managed by start_harness.sh"] + [f'{k}="{v}"' for k, v in kv.items()]
env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"[OK] Saved {env_path}")
INNER_PY
fi

set -a
[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"
set +a

if [[ "$PROXY_ONLY" -eq 1 ]]; then
  exec "$VENV_PY" -m uvicorn proxy_gateway.app:app --host 127.0.0.1 --port "$PORT"
fi

# --- Import provider credentials configured in Pi (copilot/google) — idempotent ---
mkdir -p "${REPO_ROOT}/.secrets"
"$VENV_PY" "${REPO_ROOT}/scripts/import_pi_credentials.py" --repo-root "${REPO_ROOT}" || true

# --- Backend: Docker container first; native uvicorn only for --proxy-only (dev) ---
if [[ "$PROXY_ONLY" -eq 1 ]]; then
  cd "$REPO_ROOT" && exec "$VENV_PY" -m uvicorn proxy_gateway.app:app --host 127.0.0.1 --port "$PORT"
fi

if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  if command -v docker >/dev/null 2>&1; then
    echo "Starting harness backend container (gateway + MCP-over-HTTP)..."
    ( cd "$REPO_ROOT" && docker compose up -d )
    for _ in $(seq 1 30); do
      sleep 1
      curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 && break
    done
    curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1       && echo "[OK] Harness backend container live (MCP: :${PORT}/mcp/epistemic , /mcp/orchestrator)"       || echo "[WARN] container not healthy yet; check: docker compose logs"
  else
    echo "[ERROR] :${PORT} not serving and docker not found. Use --proxy-only for native uvicorn." >&2
    exit 1
  fi
fi

# --- User-level installs (idempotent): MCP over HTTP + user instructions + skill ---
AGENT_DIR="${HOME}/.pi/agent"
mkdir -p "$AGENT_DIR/skills"
if [[ ! -f "$AGENT_DIR/mcp.json" ]]; then
  cat > "$AGENT_DIR/mcp.json" <<'MCPEOF'
{
  "mcpServers": {
    "epistemic-harness":      { "url": "http://127.0.0.1:8787/mcp/epistemic" },
    "epistemic-orchestrator": { "url": "http://127.0.0.1:8787/mcp/orchestrator" }
  }
}
MCPEOF
  echo "[OK] Wrote user-level MCP config: $AGENT_DIR/mcp.json"
fi
[[ -f "$AGENT_DIR/AGENTS.md" ]] || cp "$REPO_ROOT/AGENTS.md" "$AGENT_DIR/AGENTS.md"
USER_SKILL="$AGENT_DIR/skills/epistemic-dual-process-harness"
if [[ ! -f "$USER_SKILL/SKILL.md" ]]; then
  mkdir -p "$USER_SKILL"
  cp "$REPO_ROOT"/clients/skills/epistemic-dual-process-harness/* "$USER_SKILL/" 2>/dev/null || true
  echo "[OK] Installed user-level skill: $USER_SKILL"
fi

# --- Launch Pi: --global keeps the current working directory ---
if [[ "$GLOBAL" -eq 1 ]]; then
  echo "Launching Pi (global harness mode) in $(pwd)"
  exec pi --provider harness-router --model opencode-deepseek-v4.1-flash "$@"
else
  cd "$REPO_ROOT" && exec pi --no-skills --skill ./clients/skills/epistemic-dual-process-harness --provider harness-router --model opencode-deepseek-v4.1-flash "$@"
fi
