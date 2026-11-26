"""Every dispatch that touches files must say which plane it ran on (issues #7, #9).

Silent ambiguity is what made #7 expensive: a dispatch reported content that looked like a worktree
answer while the tool had never left the container. A result without `runner` is therefore a failure,
not a result — "I cannot tell where this ran" is not "it ran where you asked".
"""
from __future__ import annotations

from typing import Any

PLANE_TOOLS = ("dispatch_readonly", "dispatch_tooled")
PLANES = ("host", "container")


def require_plane(tool: str, result: Any) -> Any:
    """Return the result untouched when its plane is declared, else a typed refusal."""
    if tool not in PLANE_TOOLS or not isinstance(result, dict):
        return result
    if result.get("runner") in PLANES:
        return result
    return {
        "ok": False,
        "error": "plane_undeclared",
        "tool": tool,
        "message": (f"{tool} returned a result without runner=host|container, so the caller cannot "
                    f"tell which filesystem produced it. Start scripts/host_dispatch.py for host paths, "
                    f"or pass runner=local for container paths."),
        "detail": {k: str(result.get(k))[:200] for k in ("error", "via", "message") if result.get(k)},
    }
