#!/usr/bin/env bash
# ==============================================================================
# Epistemic Dual-Process Harness — One-Click Clean-Room Installer (macOS / Linux)
# Installs Pi Coding Agent, isolated Python .venv, MCP wiring, and verifies all tests.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh                  # Full install (Pi + .venv + compile + tests)
#   ./install.sh --with-proxy     # Also merge local proxy into ~/.pi/agent/models.json (with backup)
#   ./install.sh --via-npm        # Install Pi via npm (@earendil-works/pi-coding-agent)
#   ./install.sh --skip-pi        # Skip Pi installation (if already installed)
#   ./install.sh --dry-run-local  # Offline verification mode (skip network downloads)
# ==============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
PYTHON_BIN=""
INSTALL_PI=1
VIA_NPM=0
CONFIGURE_PROXY=0
DRY_RUN_LOCAL=0

for arg in "$@"; do
  case "$arg" in
    --with-proxy)    CONFIGURE_PROXY=1 ;;
    --via-npm)       VIA_NPM=1 ;;
    --skip-pi)       INSTALL_PI=0 ;;
    --dry-run-local) DRY_RUN_LOCAL=1; INSTALL_PI=0 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

log()  { printf "\033[1;34m[harness-install]\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m[OK]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m[FAIL]\033[0m %s\n" "$*" >&2; exit 1; }

# ------------------------------------------------------------------------------
# 1. Check Python >= 3.10
# ------------------------------------------------------------------------------
log "Step 1/6: Checking Python 3.10+..."
if command -v python3 >/dev/null 2>&1; then
  PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  PY_OK="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 10)))')"
  if [[ "$PY_OK" -ne 1 ]]; then
    die "Python 3.10+ is required, found Python ${PY_VER}."
  fi
  ok "Found Python ${PY_VER}"
else
  die "python3 not found on PATH. Please install Python 3.10+ first."
fi

# ------------------------------------------------------------------------------
# 2. Install Pi Coding Agent (clean-room CLI)
# ------------------------------------------------------------------------------
if [[ "$INSTALL_PI" -eq 1 ]]; then
  log "Step 2/6: Checking / installing Pi Coding Agent..."
  if command -v pi >/dev/null 2>&1; then
    ok "Pi is already installed: $(pi --version 2>/dev/null || command -v pi)"
  else
    if [[ "$VIA_NPM" -eq 1 ]]; then
      command -v npm >/dev/null 2>&1 || die "npm not found; re-run without --via-npm to use standalone installer."
      log "Installing @earendil-works/pi-coding-agent globally via npm..."
      npm install -g @earendil-works/pi-coding-agent
    else
      if command -v curl >/dev/null 2>&1; then
        log "Running official Pi standalone installer (https://pi.dev/install.sh)..."
        curl -fsSL https://pi.dev/install.sh | sh
        # Ensure common install dirs are visible in current shell
        export PATH="${HOME}/.local/bin:${HOME}/.pi/bin:${PATH}"
      elif command -v npm >/dev/null 2>&1; then
        warn "curl not found; falling back to npm install -g @earendil-works/pi-coding-agent..."
        npm install -g @earendil-works/pi-coding-agent
      else
        die "Neither curl nor npm found. Install curl or Node.js/npm to install Pi."
      fi
    fi

    if command -v pi >/dev/null 2>&1; then
      ok "Pi installed successfully: $(pi --version 2>/dev/null || command -v pi)"
    else
      warn "Pi installer finished, but 'pi' is not yet on PATH. Open a new terminal or add ~/.local/bin to PATH."
    fi
  fi
else
  log "Step 2/6: Skipping Pi installation (--skip-pi / --dry-run-local)."
fi

# ------------------------------------------------------------------------------
# 3. Create isolated Python .venv & install dependencies
# ------------------------------------------------------------------------------
log "Step 3/6: Setting up Python environment..."
if [[ "$DRY_RUN_LOCAL" -eq 1 ]]; then
  PYTHON_BIN="$(command -v python3)"
  ok "Dry-run mode: using system Python at ${PYTHON_BIN}"
else
  if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
  fi
  PYTHON_BIN="${VENV_DIR}/bin/python"
  "${PYTHON_BIN}" -m pip install --upgrade pip >/dev/null
  "${PYTHON_BIN}" -m pip install pyyaml pydantic fastapi uvicorn httpx
  ok "Dependencies installed in ${VENV_DIR}"
fi

# ------------------------------------------------------------------------------
# 4. Wire project-local .pi/mcp.json to the exact Python binary & compile AGENTS.md
# ------------------------------------------------------------------------------
log "Step 4/6: Wiring .pi/mcp.json & compiling harness.yaml -> AGENTS.md..."
mkdir -p "${REPO_ROOT}/.pi"
cat > "${REPO_ROOT}/.pi/mcp.json" <<'EOF'
{
  "mcpServers": {
    "epistemic-harness":      { "url": "http://127.0.0.1:8787/mcp/epistemic" },
    "epistemic-orchestrator": { "url": "http://127.0.0.1:8787/mcp/orchestrator" }
  }
}
EOF
"${PYTHON_BIN}" "${REPO_ROOT}/scripts/compile_clients.py"
ok "Wired .pi/mcp.json (HTTP) and compiled AGENTS.md"

# ------------------------------------------------------------------------------
# 5. Optional: safely merge local Proxy Gateway into ~/.pi/agent/models.json
# ------------------------------------------------------------------------------
if [[ "$CONFIGURE_PROXY" -eq 1 ]]; then
  log "Step 5/6: Merging local Proxy Gateway (127.0.0.1:8787) into ~/.pi/agent/models.json..."
  "${PYTHON_BIN}" - << 'PY'
from datetime import datetime
import json
from pathlib import Path
import shutil

models_path = Path.home() / ".pi" / "agent" / "models.json"
models_path.parent.mkdir(parents=True, exist_ok=True)
if models_path.exists():
    backup = models_path.with_suffix(f".json.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(models_path, backup)
    data = json.loads(models_path.read_text(encoding="utf-8"))
else:
    data = {}

providers = data.setdefault("providers", {})
providers.setdefault("harness-anthropic", {
    "baseUrl": "http://127.0.0.1:8787/anthropic",
    "api": "anthropic-messages",
    "apiKey": "$ANTHROPIC_API_KEY",
})
providers.setdefault("harness-openai", {
    "baseUrl": "http://127.0.0.1:8787/v1",
    "api": "openai-completions",
    "apiKey": "$OPENAI_API_KEY",
    "models": [{"id": "o3-mini"}, {"id": "gpt-5"}],
})
models_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Updated {models_path}")
PY
  ok "Proxy providers merged safely (existing config backed up if present)."
else
  log "Step 5/6: Skipping ~/.pi/agent/models.json merge (pass --with-proxy to enable)."
fi

# ------------------------------------------------------------------------------
# 6. Run full self-verification (Phase 1 MCP + Phase 2 Proxy + Mock Golden Evals)
# ------------------------------------------------------------------------------
log "Step 6/6: Running automated hard-constraint tests & mock Golden Eval suite..."
(
  cd "${REPO_ROOT}"
  "${PYTHON_BIN}" -m unittest discover -s tests -v
  "${PYTHON_BIN}" evals/run_evals.py --mock
)
ok "All Phase 1 + Phase 2 self-tests passed!"

if command -v pi >/dev/null 2>&1; then
  log "Running 'pi doctor' health check..."
  pi doctor || warn "pi doctor reported warnings; check provider API keys with 'pi auth check'."
fi

cat <<'DONE'

==============================================================================
# ------------------------------------------------------------------------------
# 7. Global enablement: user-level MCP/instructions/skill, shell alias, credentials, image
# ------------------------------------------------------------------------------
log "Step 7/7: Global enablement..."
AGENT_DIR="${HOME}/.pi/agent"
mkdir -p "${AGENT_DIR}/skills"
if [[ ! -f "${AGENT_DIR}/mcp.json" ]]; then
  cat > "${AGENT_DIR}/mcp.json" <<'MCPEOF'
{
  "mcpServers": {
    "epistemic-harness":      { "url": "http://127.0.0.1:8787/mcp/epistemic" },
    "epistemic-orchestrator": { "url": "http://127.0.0.1:8787/mcp/orchestrator" }
  }
}
MCPEOF
  ok "user-level mcp.json"
fi
[[ -f "${AGENT_DIR}/AGENTS.md" ]] || { cp "${REPO_ROOT}/AGENTS.md" "${AGENT_DIR}/AGENTS.md"; ok "user-level AGENTS.md"; }
USER_SKILLS="${AGENT_DIR}/skills"
for skill_dir in "${REPO_ROOT}"/clients/skills/*/; do
  name="$(basename "$skill_dir")"
  [[ -f "$skill_dir/SKILL.md" ]] || continue
  if [[ ! -f "${USER_SKILLS}/${name}/SKILL.md" ]]; then
    mkdir -p "${USER_SKILLS}/${name}"
    cp "$skill_dir"/* "${USER_SKILLS}/${name}/" 2>/dev/null || true
    ok "user-level skill: $name"
  fi
done
for rc in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
  [[ -f "$rc" ]] || continue
  grep -q "alias harness=" "$rc" || {
    printf "
alias harness='%s/start_harness.sh --global'
" "${REPO_ROOT}" >> "$rc"
    ok "harness alias -> $rc"
  }
done
mkdir -p "${REPO_ROOT}/.secrets"
USER_EXT="${AGENT_DIR}/extensions"
mkdir -p "$USER_EXT"
for ext in "${REPO_ROOT}"/extensions/*; do
  [[ -f "$ext" ]] || continue
  name="$(basename "$ext")"
  [[ -f "${USER_EXT}/${name}" ]] || { cp "$ext" "$USER_EXT/$name"; ok "extension: $name"; }
done
"${PYTHON_BIN}" "${REPO_ROOT}/scripts/import_pi_credentials.py" --repo-root "${REPO_ROOT}" || true
if command -v docker >/dev/null 2>&1; then
  ( cd "${REPO_ROOT}" && docker compose build >/dev/null 2>&1 && ok "container image built" ) || warn "docker build failed; start_harness will retry"
else
  warn "docker not found; start_harness will fall back or prompt."
fi

Installation complete! Next steps:
  1. Start Phase 2 local proxy gateway (Terminal 1):
       ./scripts/start_proxy.sh
  2. Launch Pi in this clean-room repo (Terminal 2):
       pi
     Inside Pi, run `pi mcp list` to verify `epistemic-harness` (7 tools).
  3. Run real Golden Test regression against Pi:
       .venv/bin/python evals/run_evals.py --mode json
==============================================================================
DONE