"""Deterministic Cognitive-Bias First-Pass Scanner (L3 heuristic layer).

Loads the L3 bias catalog (knowledge/l3_heuristics/cognitive_biases.yaml) and
scans text for bias markers. This is a FIRST-PASS screen only: markers are
keyword heuristics with false-positive risk, so hits must be routed to the
critic profile (system_2_plus cross-family review) before any verdict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class BiasGuard:
    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path
        self.biases: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.catalog_path.exists():
            return
        data = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8")) or {}
        for item in data.get("biases", []):
            if not item.get("scope_conditions") or not item.get("counter_examples"):
                raise ValueError(
                    f"Bias catalog {item.get('id')} violates harness.yaml L3 rules: "
                    "scope_conditions and counter_examples are mandatory."
                )
            self.biases[item["id"]] = item

    def scan(self, text: str, max_hits: int = 3) -> dict[str, Any]:
        """Return matched biases with per-marker counts and mandated corrections."""
        if not text:
            return {"matches": [], "verdict": "clean", "note": "empty text"}
        matches: list[dict[str, Any]] = []
        lowered = text.lower()
        for bias in self.biases.values():
            hit_markers = [m for m in bias.get("detection_markers", []) if m.lower() in lowered]
            if hit_markers:
                matches.append({
                    "bias_id": bias["id"],
                    "name": bias["name"],
                    "hit_markers": hit_markers,
                    "scope_conditions": bias["scope_conditions"],
                    "counter_examples": bias["counter_examples"],
                    "mandated_correction": bias["correction"],
                    "harness_mapping": bias["harness_mapping"],
                })
        matches.sort(key=lambda m: -len(m["hit_markers"]))
        matches = matches[:max_hits]
        verdict = "requires_critic_review" if matches else "clean"
        return {
            "matches": matches,
            "verdict": verdict,
            "note": (
                "First-pass L3 heuristic screen; false positives possible. "
                "Route hits to dispatch_subagent(agent_profile='critic') for cross-family verdict."
            ),
        }
