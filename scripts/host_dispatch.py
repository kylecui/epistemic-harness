#!/usr/bin/env python3
"""Host-side dispatch agent (issue #7): run dispatches on the machine that owns the files.

The orchestrator runs inside the backend container, which only sees a few bind mounts.
Dispatching against a host worktree therefore failed with a bare `not a directory: .`
(read-only) or `pi binary not found` (tooled). This agent is the other half of the
boundary: it listens on loopback on the HOST and executes exactly two operations there.

    python scripts/host_dispatch.py                # 127.0.0.1:8791
    python scripts/host_dispatch.py --port 8791 --roots D:\\work --token s3cret

    GET  /health              liveness, plane, repo root, allowed roots, pi binary
    POST /dispatch_readonly   {"task_text", "workdir", "task_id", "effort", "max_rounds"}
    POST /dispatch_tooled     {"task_text", "workdir", "profile", "model", "timeout"}

Design rules:
  * loopback bind only (default 127.0.0.1); the container reaches it through Docker
    Desktop's host.docker.internal — no host directory is mounted into the gateway.
  * `dispatch_tooled` writes files and spawns processes, so its workdir must sit inside an
    allowed root (repo root, cwd, `--roots`/`HARNESS_TOOLED_ROOTS`);
    `dispatch_readonly` only reads inside its sandbox root, so any existing directory is
    accepted, matching the host-plane behaviour it replaces.
  * optional shared token (`--token`/`HARNESS_HOST_DISPATCH_TOKEN`, header
    `X-Harness-Host-Token`): any local process can reach a loopback port, so a token is the
    cheapest way to keep it to our own container.
  * results are stamped `runner=host`, `via=host_dispatch`, so a dispatch record names the
    plane that produced it.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.host_bridge import DEFAULT_PORT, LOOPBACK_URL, TOKEN_ENV  # noqa: E402
from orchestrator.readonly_agent import dispatch_readonly as _readonly_impl  # noqa: E402
from orchestrator.tooled import _allowed_roots, _validate_workdir  # noqa: E402
from orchestrator.tooled import dispatch_tooled as _tooled_impl  # noqa: E402

SERVICE = "harness-host-dispatch"
VERSION = "1"
MAX_ROUNDS_CAP = 12
DEFAULT_TIMEOUT = 600.0


class HostDispatchService:
    """The two operations this agent offers, plus the metadata /health reports."""

    def __init__(
        self,
        repo_root: Path = REPO_ROOT,
        readonly_fn: Callable[..., dict[str, Any]] | None = None,
        tooled_fn: Callable[..., dict[str, Any]] | None = None,
        token: str | None = None,
    ) -> None:
        self.repo_root = repo_root
        self._readonly_fn = readonly_fn or _readonly_impl
        self._tooled_fn = tooled_fn or _tooled_impl
        self.token = (token if token is not None else os.getenv(TOKEN_ENV, "")).strip()

    # ------------------------------------------------------------------ metadata

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "service": SERVICE,
            "version": VERSION,
            "plane": "host",
            "pid": os.getpid(),
            "repo_root": str(self.repo_root),
            "allowed_roots": [str(p) for p in _allowed_roots()],
            "pi_binary": os.getenv("HARNESS_PI_BIN") or _which_pi(),
            "auth": "token" if self.token else "loopback-only",
        }

    def authorized(self, header_value: str | None) -> bool:
        if not self.token:
            return True
        return (header_value or "").strip() == self.token

    # ------------------------------------------------------------------ dispatch

    def dispatch_readonly(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_text = str(payload.get("task_text") or "")
        workdir = payload.get("workdir")
        if not task_text:
            return _fail("missing_task_text", "task_text is required")
        if not workdir:
            return _fail("missing_workdir", "workdir is required for a read-only dispatch")
        root = Path(str(workdir)).expanduser()
        if not root.is_dir():
            return _fail(
                "workdir_unavailable",
                f"workdir {str(root)!r} does not exist on the host plane",
            )
        rounds = min(MAX_ROUNDS_CAP, max(1, int(payload.get("max_rounds") or 6)))
        try:
            out = self._readonly_fn(
                task_text=task_text,
                workdir=root,
                task_id=str(payload.get("task_id") or "ro-1"),
                effort=payload.get("effort") or "low",
                model=payload.get("model"),
                max_rounds=rounds,
                runner="host",
                via="host_dispatch",
            )
        except TypeError as exc:
            # an injected/stubbed implementation may not accept the plane fields
            if "runner" not in str(exc) and "via" not in str(exc):
                raise
            out = self._readonly_fn(
                task_text=task_text, workdir=root,
                task_id=str(payload.get("task_id") or "ro-1"),
                effort=payload.get("effort") or "low",
                model=payload.get("model"), max_rounds=rounds,
            )
        return _stamp(out)

    def dispatch_tooled(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_text = str(payload.get("task_text") or "")
        if not task_text:
            return _fail("missing_task_text", "task_text is required")
        workdir = payload.get("workdir")
        try:
            resolved = _validate_workdir(str(workdir) if workdir else None)
        except (ValueError, PermissionError) as exc:
            return _fail(
                "workdir_rejected",
                f"{exc} — allowed roots: {[str(p) for p in _allowed_roots()]}",
            )
        timeout = min(3600.0, max(30.0, float(payload.get("timeout") or DEFAULT_TIMEOUT)))
        out = self._tooled_fn(
            task_text=task_text,
            workdir=str(resolved),
            profile=str(payload.get("profile") or "coder"),
            model=payload.get("model"),
            timeout=timeout,
        )
        return _stamp(out)


def _which_pi() -> str | None:
    import shutil

    return shutil.which("pi")


def _fail(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "status": "rejected", "error": code, "message": message,
            "runner": "host", "via": "host_dispatch"}


def _stamp(out: dict[str, Any]) -> dict[str, Any]:
    if isinstance(out, dict):
        out["runner"] = "host"
        out["via"] = "host_dispatch"
        if "ok" not in out:
            out["ok"] = out.get("status") in ("ok", "done", None)
    return out


def make_handler(service: HostDispatchService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"{SERVICE}/{VERSION}"
        protocol_version = "HTTP/1.1"

        def _json(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path.split("?")[0] in ("/health", "/"):
                self._json(200, service.health())
                return
            self._json(404, {"ok": False, "error": "not_found", "path": self.path})

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            route = self.path.split("?")[0]
            if route not in ("/dispatch_readonly", "/dispatch_tooled"):
                self._json(404, {"ok": False, "error": "not_found", "path": self.path})
                return
            if not service.authorized(self.headers.get("X-Harness-Host-Token")):
                self._json(401, {"ok": False, "error": "host_dispatch_unauthorized",
                                 "message": f"set X-Harness-Host-Token ({TOKEN_ENV}) on both sides"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("payload must be a JSON object")
            except (ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"ok": False, "error": "bad_request", "message": str(exc)})
                return
            try:
                if route == "/dispatch_readonly":
                    result = service.dispatch_readonly(payload)
                else:
                    result = service.dispatch_tooled(payload)
            except Exception as exc:  # noqa: BLE001 - report, never drop the connection
                self._json(500, {"ok": False, "error": "host_dispatch_failed",
                                 "message": f"{type(exc).__name__}: {exc}",
                                 "runner": "host", "via": "host_dispatch"})
                return
            self._json(200, result)

        def log_message(self, fmt: str, *args: Any) -> None:  # quieter than the default
            sys.stderr.write(f"[host-dispatch] {self.address_string()} {fmt % args}\n")
            sys.stderr.flush()

    return Handler


def build_server(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    service: HostDispatchService | None = None,
) -> ThreadingHTTPServer:
    service = service or HostDispatchService()
    server = ThreadingHTTPServer((host, port), make_handler(service))
    server.daemon_threads = True
    return server


def main() -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="Host-side dispatch agent for the harness orchestrator")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (loopback by default)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--roots", action="append", default=[],
                    help="extra writable root for dispatch_tooled (repeatable)")
    ap.add_argument("--token", default=None,
                    help=f"shared token required from callers (default: ${TOKEN_ENV})")
    args = ap.parse_args()

    if args.roots:
        extra = os.pathsep.join(args.roots)
        current = os.getenv("HARNESS_TOOLED_ROOTS", "").strip()
        os.environ["HARNESS_TOOLED_ROOTS"] = f"{current}{os.pathsep}{extra}" if current else extra

    service = HostDispatchService(token=args.token)
    server = build_server(args.host, args.port, service)
    bound = server.server_address
    print(f"{SERVICE} {VERSION} listening on http://{bound[0]}:{bound[1]}")
    print(f"  plane=host repo={service.repo_root}")
    print(f"  pi binary: {service.health()['pi_binary'] or 'MISSING — dispatch_tooled will fail'}")
    print(f"  writable roots: {[str(p) for p in _allowed_roots()]}")
    print(f"  auth: {service.health()['auth']}")
    print(f"  container reaches it at http://host.docker.internal:{bound[1]}")
    print("  endpoints: GET /health, POST /dispatch_readonly, POST /dispatch_tooled")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
