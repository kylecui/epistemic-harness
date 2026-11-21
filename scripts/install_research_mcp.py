#!/usr/bin/env python3
"""Install the bigmodel (Zhipu GLM Coding Plan) research MCP servers into an MCP client config.

Why this exists: the harness contract now requires external retrieval before design
or selection answers (harness.yaml → research_discipline). Retrieval needs tools, so
this script wires them in without ever committing a key.

Servers (see docs/research-capability.md for the source docs):
  web-search-prime  https://open.bigmodel.cn/api/mcp/web_search_prime/mcp   tool: webSearchPrime
  web-reader        https://open.bigmodel.cn/api/mcp/web_reader/mcp         tool: webReader
  zread             https://open.bigmodel.cn/api/mcp/zread/mcp              tools: search_doc / get_repo_structure / read_file
  zai-mcp-server    npx -y @z_ai/mcp-server (local stdio, needs Z_AI_API_KEY) tools: ui_to_image, ocr, diagram, video ...

Usage:
    export ZHIPU_API_KEY=...           # required for the three remote servers
    export Z_AI_API_KEY=...            # optional, local vision server
    python scripts/install_research_mcp.py --target pi [--dry-run]
    python scripts/install_research_mcp.py --target opencode

The script is idempotent: it merges entries and leaves other servers untouched.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REMOTE_SERVERS = {
    "web-search-prime": "https://open.bigmodel.cn/api/mcp/web_search_prime/mcp",
    "web-reader": "https://open.bigmodel.cn/api/mcp/web_reader/mcp",
    "zread": "https://open.bigmodel.cn/api/mcp/zread/mcp",
}


def _targets() -> dict[str, Path]:
    home = Path.home()
    return {
        "pi": home / ".pi" / "agent" / "mcp.json",
        "claude": home / ".claude.json",
        "opencode": home / ".config" / "opencode" / "opencode.json",
    }


def _pi_entries(token: str, vision_key: str | None) -> dict:
    entries: dict[str, dict] = {
        name: {"url": url, "headers": {"Authorization": f"Bearer {token}"}}
        for name, url in REMOTE_SERVERS.items()
    }
    if vision_key:
        entries["zai-mcp-server"] = {
            "command": "npx",
            "args": ["-y", "@z_ai/mcp-server"],
            "env": {"Z_AI_API_KEY": vision_key},
        }
    return entries


def _claude_entries(token: str, vision_key: str | None) -> dict:
    entries: dict[str, dict] = {
        name: {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {token}"}}
        for name, url in REMOTE_SERVERS.items()
    }
    if vision_key:
        entries["zai-mcp-server"] = {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@z_ai/mcp-server"],
            "env": {"Z_AI_API_KEY": vision_key},
        }
    return entries


def _opencode_entries(token: str, vision_key: str | None) -> dict:
    entries: dict[str, dict] = {
        name: {"type": "remote", "url": url, "headers": {"Authorization": f"Bearer {token}"}}
        for name, url in REMOTE_SERVERS.items()
    }
    if vision_key:
        entries["zai-mcp-server"] = {
            "type": "local",
            "command": ["npx", "-y", "@z_ai/mcp-server"],
            "environment": {"Z_AI_API_KEY": vision_key},
            "enabled": True,
        }
    return entries


def build_config(target: str, existing: dict, token: str, vision_key: str | None) -> dict:
    if target == "opencode":
        cfg = dict(existing or {})
        cfg.setdefault("$schema", "https://opencode.ai/config.json")
        mcp = dict(cfg.get("mcp") or {})
        mcp.update(_opencode_entries(token, vision_key))
        cfg["mcp"] = mcp
        return cfg

    cfg = dict(existing or {})
    servers = dict(cfg.get("mcpServers") or {})
    servers.update(_claude_entries(token, vision_key) if target == "claude" else _pi_entries(token, vision_key))
    cfg["mcpServers"] = servers
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["pi", "claude", "opencode"], default="pi")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--path", help="override the config path")
    args = ap.parse_args()

    token = os.environ.get("ZHIPU_API_KEY") or os.environ.get("BIGMODEL_API_KEY")
    if not token:
        print("ZHIPU_API_KEY is not set. Get one from the coding plan console, then re-run.", file=sys.stderr)
        return 2
    vision_key = os.environ.get("Z_AI_API_KEY")

    path = Path(args.path) if args.path else _targets()[args.target]
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"refusing to overwrite unparsable config {path}: {exc}", file=sys.stderr)
            return 3

    merged = build_config(args.target, existing, token, vision_key)
    rendered = json.dumps(merged, ensure_ascii=False, indent=2)

    if args.dry_run:
        print(rendered)
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + "\n", encoding="utf-8")
    print(f"Updated {path} ({args.target}): {', '.join(sorted({*REMOTE_SERVERS, *(['zai-mcp-server'] if vision_key else [])}))}")
    print("Restart the client, then verify with: pi mcp list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
