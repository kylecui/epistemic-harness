"""Cross-family exclusion resolution (P0-1).

The session-scoped drafter-pool map only works when the critic call reuses the
drafter's session id. Sub-agent dispatches use per-subtask ids, so exclusion is
also driven by explicit headers:

    X-Harness-Exclude-Pool: <pool_id>      highest precedence
    X-Harness-Exclude-Model: <model_key>   mapped to that model's shared pool
    (fallback) session-last-pool when the routing decision is a critic turn
"""

from __future__ import annotations

from typing import Any


def resolve_excluded_pool(
    headers: dict[str, str],
    qm: Any,
    session_last_pool: dict[str, str],
    sess_id: str,
    is_critic: bool,
) -> str | None:
    hdrs = {str(k).lower(): str(v).strip() for k, v in (headers or {}).items()}

    explicit_pool = hdrs.get("x-harness-exclude-pool")
    if explicit_pool:
        return explicit_pool

    explicit_model = hdrs.get("x-harness-exclude-model")
    if explicit_model and explicit_model in getattr(qm, "models", {}):
        pool_id, _ = qm.pool_for_model(explicit_model)
        return pool_id

    if is_critic:
        return session_last_pool.get(sess_id)
    return None
