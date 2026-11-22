#!/usr/bin/env python3
"""Capability matrix (R4): which (model, effort, tier) combinations the gateway will actually serve.

The main agent can only schedule combinations that are legal and that have
credentials. This tool prints the matrix and validates it against the rules the
gateway enforces:

  * effort above a model's `max_effort` is clamped (evidence-based, e.g. the
    opencode-deepseek empty-content bug) — such a combo is reported, not hidden;
  * `avoid_in_peak_for_tiers` lists tiers the model yields during its pool's
    peak windows — those combos exist but cost more in peak;
  * an API key (env or .env) decides whether the combo is usable right now.

Usage:
    python scripts/capability_matrix.py
    python scripts/capability_matrix.py --json
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"
EFFORTS = ["minimal", "low", "medium", "high"]
ORDER = {e: i for i, e in enumerate(EFFORTS)}


def _load_env() -> dict[str, str]:
    env: dict[str, str] = dict(os.environ)
    dotenv = REPO_ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip().strip('"'))
    return env


def _auth_credentials_present(auth: str | None, env: dict[str, str]) -> bool:
    """OAuth-backed models need their token file, not just the `auth:` label —
    a fresh clone showed 'ok' for Copilot with no .secrets at all (install test,
    2026-11-21). Check what each auth type actually needs."""
    if not auth:
        return False
    if auth == "copilot":
        if env.get("GITHUB_COPILOT_TOKEN") or env.get("COPILOT_TOKEN"):
            return True
        return (REPO_ROOT / ".secrets" / "github-copilot.json").exists()
    return True  # unknown auth types: keep the label-level answer, flagged in docs


def build_matrix(policy_path: Path = POLICY, env: dict[str, str] | None = None) -> dict:
    env = env if env is not None else _load_env()
    spec = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    models = spec.get("models") or {}
    pools = spec.get("pools") or {}
    rows: list[dict] = []
    for name, m in models.items():
        max_effort = m.get("max_effort")
        max_idx = ORDER.get(max_effort, len(EFFORTS) - 1)
        key_env = m.get("api_key_env")
        auth = m.get("auth")
        has_key = _auth_credentials_present(auth, env) or bool(key_env and env.get(key_env))
        pool = pools.get(m.get("pool") or "", {})
        rows.append({
            "model": name,
            "pool": m.get("pool"),
            "protocol": m.get("protocol"),
            "auth": auth or "api_key",
            "key_env": key_env,
            "credentials_present": has_key,
            "upstream_model": m.get("upstream_model"),
            "cost_out_per_1m": (m.get("cost_per_1m") or {}).get("output"),
            "max_effort": max_effort,
            "efforts_allowed": EFFORTS[: max_idx + 1],
            "efforts_clamped": EFFORTS[max_idx + 1:],
            "avoid_in_peak_for_tiers": m.get("avoid_in_peak_for_tiers") or [],
            "last_option_pool": bool(pool.get("last_option")),
        })
    return {
        "policy": str(policy_path),
        # Honest drift marker (workplan §三.6): everything in this matrix is a
        # LOCAL estimate (policy + credential presence). The gateway's quota
        # ledger only counts traffic it routed; upstream-side quota/limits are
        # never observed. Never present these numbers as upstream truth.
        "estimate_only": True,
        "models": rows,
        "rules": {
            "free_combination": "any (model, effort <= max_effort) is schedulable; efforts above "
                                "max_effort are clamped by the gateway (X-Harness-Effort override "
                                "cannot raise effort past max_effort)",
            "tier_availability": "avoid_in_peak_for_tiers lists tiers yielded during the pool's "
                                 "peak windows (active_peak_avoidance)",
        },
    }


def validate_routing(routing_path: Path, matrix: dict) -> list[str]:
    """Check a task routing table against the capability matrix (R2 hardening)."""
    sys.path.insert(0, str(REPO_ROOT))
    from orchestrator.task_router import validate_against_capability  # local import: scripts-only dep
    spec = yaml.safe_load(Path(routing_path).read_text(encoding="utf-8")) or {}
    return validate_against_capability(spec, matrix)


def main() -> int:
    routing = None
    argv = [a for a in sys.argv[1:]]
    if "--validate-routing" in argv:
        idx = argv.index("--validate-routing")
        routing = Path(argv[idx + 1]) if idx + 1 < len(argv) else REPO_ROOT / "config" / "task_routing.yaml"
        argv = argv[:idx] + argv[idx + 2:]
    matrix = build_matrix()
    if routing is not None:
        violations = validate_routing(routing, matrix)
        hard = [v for v in violations if not v.startswith("warning:")]
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        if hard:
            print(f"routing table {routing}: {len(hard)} violation(s)", file=sys.stderr)
            return 1
        print(f"routing table {routing}: ok ({len(violations)} overlap warning(s))")
        return 0
    if "--json" in argv:
        print(json.dumps(matrix, ensure_ascii=False, indent=2))
        return 0
    print(f"{'model':34s} {'pool':22s} {'cred':4s} {'max_effort':10s} efforts allowed")
    for row in matrix["models"]:
        allowed = ",".join(e[0] for e in row["efforts_allowed"])
        clamped = f"  clamped:{','.join(row['efforts_clamped'])}" if row["efforts_clamped"] else ""
        print(f"{row['model']:34s} {row['pool'] or '?':22s} "
              f"{'ok' if row['credentials_present'] else 'MISS':4s} "
              f"{row['max_effort'] or '-':10s} {allowed}{clamped}")
    missing = [r["model"] for r in matrix["models"] if not r["credentials_present"]]
    if missing:
        print(f"note: no credentials for {missing} — combos exist but are not usable right now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
