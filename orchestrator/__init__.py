"""Sub-agent orchestration layer for the Epistemic Harness (Phase 3).

The main agent acts as a pure controller: understand -> decompose -> dispatch
-> converge. Concrete subtask execution is delegated to sub-agents through the
local proxy gateway, which routes each sub-agent to an adaptive cognitive tier
and model. Skill auto-attach removes the need for manual skill invocation.
"""

from orchestrator.bias_guard import BiasGuard  # noqa: F401,E402
from orchestrator.dispatch import dispatch_subtask  # noqa: F401,E402
from orchestrator.planner import classify_task  # noqa: F401,E402
