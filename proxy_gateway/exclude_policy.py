"""Cross-family exclusion resolution (P0-1) with session-level fallback.

Resolution order (first hit wins):
  1. X-Harness-Exclude-Pool   — explicit pool, highest precedence
  2. X-Harness-Exclude-Model  — mapped to that model's shared pool
  3. exact session id         — the drafter used the same session (same-client critic pass)
  4. session id without a critic suffix (…-critic / -review / -audit)
  5. last drafter pool seen by this gateway instance (client-agnostic fallback)

Steps 3–5 only apply to critic turns. This keeps cross-family review working for
clients that know nothing about the exclude headers (OpenCode, Claude Code, Codex).
"""

from __future__ import annotations

import re
from typing import Any

_CRITIC_SUFFIX = re.compile(r"-(?:critic|review|audit|judge)$", re.I)


def resolve_excluded_pool(
    headers: dict[str, str],
    qm: Any,
    session_last_pool: dict[str, str],
    sess_id: str,
    is_critic: bool,
    last_drafter_pool: str | None = None,
) -> str | None:
    hdrs = {str(k).lower(): str(v).strip() for k, v in (headers or {}).items()}

    explicit_pool = hdrs.get("x-harness-exclude-pool")
    if explicit_pool:
        return explicit_pool

    explicit_model = hdrs.get("x-harness-exclude-model")
    if explicit_model and explicit_model in getattr(qm, "models", {}):
        pool_id, _ = qm.pool_for_model(explicit_model)
        return pool_id

    if not is_critic:
        return None

    if sess_id in session_last_pool:
        return session_last_pool[sess_id]

    base = _CRITIC_SUFFIX.sub("", sess_id or "")
    if base and base in session_last_pool:
        return session_last_pool[base]

    return last_drafter_pool
