"""Skill Registry: proactive skill discovery, matching, and human-gated registration.

Philosophy (requirement: "no manual skill invocation"):
  - Skills are matched and attached AUTOMATICALLY by code at dispatch time.
  - New skills never mutate the live registry directly; they queue into
    skill_queue/pending.yaml for explicit human approval (same PR-gate
    philosophy as L1/L2 promotions).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class SkillRegistry:
    def __init__(self, registry_path: Path, queue_path: Path) -> None:
        self.registry_path = registry_path
        self.queue_path = queue_path
        self.skills: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.registry_path.exists():
            return
        from orchestrator.fsretry import with_retry
        text = with_retry(lambda: self.registry_path.read_text(encoding="utf-8"))
        data = yaml.safe_load(text) or {}
        for item in data.get("skills", []):
            self._validate(item)
            self.skills[item["id"]] = item

    @staticmethod
    def _validate(item: dict[str, Any]) -> None:
        for field in ("id", "name", "description", "content"):
            if not item.get(field):
                raise ValueError(f"Skill entry missing mandatory field '{field}': {item!r}")

    def query(self, query: str = "", limit: int = 5) -> list[dict[str, Any]]:
        """Keyword search over id/name/description/tags/triggers.

        CJK runs are additionally split into bigrams — Chinese queries rarely
        contain spaces, so without this the whole phrase becomes one token and
        never matches ('看看状态' vs trigger '状态'). Same tokenization idea as
        the memory index, kept dependency-free.
        """
        tokens = [t.lower() for t in query.split() if t.strip()]
        for raw in list(tokens):
            tokens.extend(self._cjk_bigrams(raw))
        scored: list[tuple[int, dict[str, Any]]] = []
        for skill in self.skills.values():
            if not tokens:
                scored.append((0, skill))
                continue
            haystack = " ".join(
                str(skill.get(k, "")) for k in ("id", "name", "description")
            ).lower() + " " + " ".join(skill.get("tags", [])) + " " + " ".join(skill.get("triggers", []))
            score = sum(1 for t in tokens if t in haystack)
            if score:
                scored.append((score, skill))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:limit]]

    @staticmethod
    def _cjk_bigrams(text: str) -> list[str]:
        import re

        out: list[str] = []
        for run in re.findall(r"[\u3400-\u9fff]+", text):
            if len(run) == 1:
                out.append(run)
            else:
                out.extend(run[i:i + 2] for i in range(len(run) - 1))
        return out

    def match_for_task(self, task_text: str, limit: int = 2) -> list[dict[str, Any]]:
        """Auto-attach candidates for a task: full task text as query, filter by score >= 1."""
        matches = self.query(task_text, limit=limit)
        if not matches:
            return []
        # Re-score with the full text (multi-word tasks hit more tokens).
        return matches

    def register_pending(self, name: str, description: str, content: str,
                         tags: list[str] | None = None,
                         triggers: list[str] | None = None,
                         tier_hint: str | None = None) -> dict[str, Any]:
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        existing = yaml.safe_load(self.queue_path.read_text(encoding="utf-8")) if self.queue_path.exists() else {}
        queue: list[dict[str, Any]] = (existing or {}).get("pending_skills", [])
        entry = {
            "skill_id": f"SKILL-PENDING-{len(queue) + 1:03d}",
            "name": name,
            "description": description,
            "content": content,
            "tags": tags or [],
            "triggers": triggers or [],
            "tier_hint": tier_hint,
            "status": "awaiting_human_approval",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        queue.append(entry)
        self.queue_path.write_text(
            yaml.safe_dump({"pending_skills": queue}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return {
            "queued": entry,
            "message": "Skills never write the live registry directly; queued in skill_queue/pending.yaml for human review.",
        }
