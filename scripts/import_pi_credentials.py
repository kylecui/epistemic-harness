#!/usr/bin/env python3
"""Import provider credentials configured in Pi (~/.pi/agent/auth.json) into the harness router.

Mappings (evidence: Pi stores OAuth/api-key entries per provider):
  github-copilot.refresh -> .secrets/github-copilot.json  ({github: <token>})
  google.key (type=api_key) -> .env GEMINI_API_KEY (upsert, other lines preserved)

Run on every harness start (cheap, idempotent). Prints what changed; exits 0 always
(credential import is best-effort and must never block startup).

Usage: python scripts/import_pi_credentials.py [--repo-root PATH]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _strip(v: str | None) -> str | None:
    return v.strip().strip('"').strip("'") if v else v


def load_pi_auth(home: Path) -> dict:
    path = home / ".pi" / "agent" / "auth.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def upsert_env_line(env_path: Path, key: str, value: str) -> bool:
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
    out, changed = [], False
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            found = True
            new_line = f'{key}="{value}"'
            if line != new_line:
                changed = True
            out.append(new_line)
        else:
            out.append(line)
    if not found:
        out.append(f'{key}="{value}"')
        changed = True
    if changed:
        env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    repo = Path(args.repo_root)
    home = Path.home()
    auth = load_pi_auth(home)
    changes: list[str] = []

    copilot = auth.get("github-copilot") or {}
    gh_token = _strip(copilot.get("refresh") or "")
    if gh_token:
        secrets_dir = repo / ".secrets"
        target = secrets_dir / "github-copilot.json"
        payload = json.dumps({"github": gh_token}, ensure_ascii=False)
        if not target.is_file() or target.read_text(encoding="utf-8").strip() != payload:
            secrets_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
            changes.append("github-copilot -> .secrets/github-copilot.json")

    google = auth.get("google") or {}
    gkey = _strip(google.get("key") or "")
    if google.get("type") == "api_key" and gkey:
        if upsert_env_line(repo / ".env", "GEMINI_API_KEY", gkey):
            changes.append("google api_key -> .env GEMINI_API_KEY")

    others = [k for k in auth if k not in ("github-copilot", "google")]
    if others:
        print(f"[harness] auth.json 还存在未映射的 provider: {', '.join(others)}（暂无自动导入规则）")

    if changes:
        for c in changes:
            print(f"[harness] 已导入/更新凭据: {c}")
        print("[harness] 若容器正在运行，需重建以加载新 env: docker compose up -d --force-recreate")
    else:
        print("[harness] Pi 凭据已同步，无变化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
