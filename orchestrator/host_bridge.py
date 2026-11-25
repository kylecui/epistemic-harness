"""Host-side dispatch bridge (issue #7): make the container/host boundary explicit.

The orchestrator usually runs inside the backend container, which sees only a few bind
mounts. Host worktrees (`D:\\MyWorkSpaces\\...`) are not there, so `dispatch_readonly`
died with a bare `not a directory: .` and `dispatch_tooled` answered
`pi binary not found`. Mounting the host tree into the gateway would buy that convenience
with a security surface the architecture deliberately avoided.

Instead:

  * a small host-side agent (`scripts/host_dispatch.py`) runs the dispatch ON THE HOST,
    on loopback only, and never gets a mount of its own;
  * this module is the client half: it decides which plane should execute a dispatch,
    forwards the request over loopback when the local plane cannot see the path, and
    otherwise names the boundary and the remedy instead of leaking an `ENOENT`.

The container reaches the host agent through Docker Desktop's `host.docker.internal`
(measured 2026-11-25: host listener on 127.0.0.1:8791 answered from inside
`harness-backend` via `host.docker.internal`, while the container's own 127.0.0.1 did not).
Override with `HARNESS_HOST_DISPATCH_URL` when the layout differs (Linux host-gateway,
a remote workstation, another port).

Every result carries two fields so the plane is auditable, not implicit:

  runner  host | container   — where the code actually ran
  via     in-process | host_dispatch — how the MCP layer got there
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any
import urllib.error
import urllib.request

DEFAULT_PORT = 8791
LOOPBACK_URL = f"http://127.0.0.1:{DEFAULT_PORT}"
CONTAINER_URL = f"http://host.docker.internal:{DEFAULT_PORT}"

URL_ENV = "HARNESS_HOST_DISPATCH_URL"
TOKEN_ENV = "HARNESS_HOST_DISPATCH_TOKEN"
PLANE_ENV = "HARNESS_PLANE"
START_COMMAND = "python scripts/host_dispatch.py"

BOUNDARY = (
    "the backend container sees selective bind mounts, not the host filesystem; "
    "host worktrees are dispatched by the host-side agent (scripts/host_dispatch.py) "
    "over loopback, so no host directory is mounted into the gateway"
)


# --------------------------------------------------------------------------- plane


def plane() -> str:
    """Which execution plane is this process on: 'host' or 'container'."""
    forced = os.getenv(PLANE_ENV, "").strip().lower()
    if forced in ("host", "container"):
        return forced
    if Path("/.dockerenv").exists():
        return "container"
    return "host"


def in_container() -> bool:
    return plane() == "container"


def base_url() -> str:
    explicit = os.getenv(URL_ENV, "").strip()
    if explicit:
        return explicit.rstrip("/")
    return CONTAINER_URL if in_container() else LOOPBACK_URL


def pi_binary() -> str | None:
    return os.getenv("HARNESS_PI_BIN") or shutil.which("pi")


def local_dir_usable(workdir: str | None) -> bool:
    """True when THIS plane can see `workdir` as a directory (never raises)."""
    if not workdir:
        return True
    try:
        return Path(workdir).expanduser().is_dir()
    except OSError:
        return False


# ------------------------------------------------------------------------ errors


class HostDispatchUnavailable(RuntimeError):
    """The host agent could not be reached, so the dispatch has no plane to run on."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"host dispatch agent unreachable at {url}: {reason}")

    def as_result(self, kind: str, workdir: str | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "unavailable",
            "error": "host_dispatch_unavailable",
            "kind": kind,
            "workdir": workdir,
            "runner": None,
            "via": "host_dispatch",
            "host_dispatch_url": self.url,
            "boundary": BOUNDARY,
            "message": (f"{kind} cannot run on this plane: {self.reason}"),
            "remedy": (
                f"start the host-side agent on the host machine: `{START_COMMAND}` "
                f"(it binds {LOOPBACK_URL} and the container reaches it at {CONTAINER_URL}); "
                f"point elsewhere with {URL_ENV}=http://host:port"
            ),
        }


# ------------------------------------------------------------------------- client


def _request(endpoint: str, payload: dict[str, Any] | None, timeout: float,
             url: str | None = None) -> dict[str, Any]:
    target = f"{(url or base_url()).rstrip('/')}{endpoint}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(target, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    token = os.getenv(TOKEN_ENV, "").strip()
    if token:
        req.add_header("X-Harness-Host-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - loopback only
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "status": "http_error", "error": "host_dispatch_http_error",
                "http_status": exc.code, "message": detail, "host_dispatch_url": url or base_url()}
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise HostDispatchUnavailable(url or base_url(), str(reason)) from exc
    try:
        out = json.loads(body)
    except json.JSONDecodeError:
        return {"ok": False, "status": "bad_response", "error": "host_dispatch_bad_response",
                "message": body[:300], "host_dispatch_url": url or base_url()}
    if isinstance(out, dict):
        out.setdefault("host_dispatch_url", url or base_url())
    return out if isinstance(out, dict) else {"ok": False, "error": "host_dispatch_bad_response",
                                              "message": body[:300]}


def probe(timeout: float = 1.5, url: str | None = None) -> dict[str, Any] | None:
    """Health of the host agent, or None when it is not reachable."""
    target = f"{(url or base_url()).rstrip('/')}/health"
    try:
        with urllib.request.urlopen(target, timeout=timeout) as resp:  # noqa: S310 - loopback only
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError):
        return None


def forward(kind: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """POST a dispatch to the host agent and stamp the runner it actually used."""
    endpoint = "/dispatch_readonly" if kind == "readonly" else "/dispatch_tooled"
    out = _request(endpoint, payload, timeout)
    out["runner"] = "host"
    out["via"] = "host_dispatch"
    return out


# ---------------------------------------------------------------------- planning


def plan_plane(kind: str, workdir: str | None = None, requested: str = "auto") -> tuple[str, str]:
    """Decide where a dispatch should execute. Returns (choice, human reason).

    choice "local"  — run in this process (runner = the plane this process is on)
    choice "host"   — hand off to the host-side agent (runner = "host")
    """
    requested = (requested or "auto").strip().lower()
    if requested in ("local", "host"):
        return requested, f"explicit runner={requested}"
    here = plane()
    if kind == "tooled":
        if here == "container":
            return "host", ("tooled sub-agents spawn the `pi` binary against a real host "
                            "worktree; the container has neither")
        if not pi_binary():
            return "host", "no `pi` binary on this plane; handing off to the host dispatch agent"
        return "local", "`pi` binary and worktree visible on this plane"
    if workdir and not local_dir_usable(workdir):
        return "host", f"workdir {workdir!r} is not a directory on the {here} plane"
    return "local", "workdir readable on this plane"


# ------------------------------------------------------------------ entry points


def dispatch_readonly_routed(
    task_text: str,
    workdir: str,
    task_id: str = "ro-1",
    effort: str = "low",
    model: str | None = None,
    max_rounds: int = 6,
    runner: str = "auto",
) -> dict[str, Any]:
    """Read-only dispatch, run here or on the host agent when the path is not here."""
    choice, reason = plan_plane("readonly", workdir, runner)
    payload = {"task_text": task_text, "workdir": workdir, "task_id": task_id,
               "effort": effort, "model": model, "max_rounds": int(max_rounds)}
    if choice == "host":
        timeout = max(120.0, min(900.0, 120.0 * max(1, int(max_rounds)) + 60.0))
        try:
            out = forward("readonly", payload, timeout)
        except HostDispatchUnavailable as exc:
            return exc.as_result("readonly", workdir)
        out["plane_reason"] = reason
        return out

    from orchestrator.readonly_agent import dispatch_readonly as local_readonly

    try:
        out = local_readonly(task_text=task_text, workdir=workdir, task_id=task_id,
                             effort=effort, model=model, max_rounds=int(max_rounds),
                             runner=plane(), via="in-process")
    except OSError as exc:
        # The local plane cannot see the tree: name the boundary, do not leak ENOENT.
        return HostDispatchUnavailable(base_url(), f"{type(exc).__name__}: {exc}").as_result(
            "readonly", workdir)
    out["runner"] = plane()
    out["via"] = "in-process"
    out["plane_reason"] = reason
    return out


def dispatch_tooled_routed(
    task_text: str,
    workdir: str | None = None,
    profile: str = "coder",
    model: str | None = None,
    timeout: float = 600.0,
    runner: str = "auto",
) -> dict[str, Any]:
    """Tooled dispatch (isolated `pi` process), run here or on the host agent."""
    choice, reason = plan_plane("tooled", workdir, runner)
    payload = {"task_text": task_text, "workdir": workdir, "profile": profile,
               "model": model, "timeout": float(timeout)}
    if choice == "host":
        try:
            out = forward("tooled", payload, float(timeout) + 60.0)
        except HostDispatchUnavailable as exc:
            return exc.as_result("tooled", workdir)
        out["plane_reason"] = reason
        return out

    from orchestrator.tooled import dispatch_tooled as local_tooled

    out = local_tooled(task_text=task_text, workdir=workdir, profile=profile,
                       model=model, timeout=float(timeout))
    out["runner"] = plane()
    out["via"] = "in-process"
    out["plane_reason"] = reason
    return out
