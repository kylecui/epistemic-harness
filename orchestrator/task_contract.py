"""Task contract (G1): the loop's goal-side anchor.

The exit gate could only verify "the checks I configured are not red". That is
not the same as "the goal is closed", and it is why a task could look green and
still be unfinished. A task contract is written when work starts, so the gate has
an explicit predicate list to close against.

Shape of `.pi/task_contract.json`:

    {
      "task_id": "issue-2-gate-evidence",
      "goal": "quantified claims must be backed by executed evidence",
      "stopping_rule": "all predicates green and no unbound claim",
      "predicates": [
        {"id": "P1", "statement": "TC-16..19 pass", "check": "unit_tests", "required": true}
      ]
    }

A predicate is closed only when a check with the same name actually ran in the
verdict. Naming a check that never executed is `check_not_executed` — the same
"claimed but not verified" failure the gate exists to stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

CONTRACT_REL = Path(".pi") / "task_contract.json"


@dataclass
class Predicate:
    id: str
    statement: str
    check: str
    required: bool = True


@dataclass
class TaskContract:
    task_id: str
    goal: str
    predicates: list[Predicate] = field(default_factory=list)
    stopping_rule: str = "all predicates green and no unbound claim"
    dispatch_required: bool = False  # controller-only enforcement (extension-side)
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskContract":
        preds = [
            Predicate(
                id=str(p.get("id") or f"P{i + 1}"),
                statement=str(p.get("statement") or ""),
                check=str(p.get("check") or ""),
                required=bool(p.get("required", True)),
            )
            for i, p in enumerate(data.get("predicates") or [])
        ]
        return cls(
            task_id=str(data.get("task_id") or "task"),
            goal=str(data.get("goal") or ""),
            predicates=preds,
            stopping_rule=str(data.get("stopping_rule") or "all predicates green and no unbound claim"),
            dispatch_required=bool(data.get("dispatch_required", False)),
            created_at=str(data.get("created_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load(repo_dir: Path) -> TaskContract | None:
    path = Path(repo_dir) / CONTRACT_REL
    if not path.exists():
        return None
    try:
        return TaskContract.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def save(repo_dir: Path, contract: TaskContract) -> Path:
    path = Path(repo_dir) / CONTRACT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    contract.created_at = contract.created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(contract.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def unclosed(contract: TaskContract, executed: list[str], failed: list[str]) -> list[dict[str, Any]]:
    """Predicates not backed by a successful executed check."""
    items: list[dict[str, Any]] = []
    for pred in contract.predicates:
        if not pred.required:
            continue
        if pred.check not in executed:
            items.append({"id": pred.id, "check": pred.check, "status": "check_not_executed",
                          "statement": pred.statement})
        elif pred.check in failed:
            items.append({"id": pred.id, "check": pred.check, "status": "check_failed",
                          "statement": pred.statement})
    return items
