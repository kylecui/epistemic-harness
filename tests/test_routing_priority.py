"""Routing-chain priority contract (user requirement 2026-11-24).

Sub-agents must prefer: zhipu > kimi > github copilot > google > ... > opencode.
OpenCode (deepseek-v4.1-flash) is the LAST-RESORT fallback for sub-agents; the
main agent still reaches it first because it is passed as `requested_model`,
which select_candidates promotes to the head at call time.

These tests pin the ordering so a future policy edit cannot silently invert it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"

FAMILY_ORDER = ("zhipu", "kimi", "copilot", "google", "opencode")


def _family(model_key: str) -> str:
    for fam in FAMILY_ORDER:
        if model_key.startswith(fam):
            return fam
    return "other"


class RoutingPriorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
        cls.chains = cls.policy["routing_chains"]
        cls.models = cls.policy["models"]

    def test_every_referenced_model_exists(self):
        for tier, chain in self.chains.items():
            for model_key in chain:
                self.assertIn(model_key, self.models, f"{tier} references unknown model {model_key}")

    def test_opencode_is_last_in_every_chain(self):
        for tier, chain in self.chains.items():
            self.assertEqual(_family(chain[-1]), "opencode", f"{tier} must end with the opencode fallback: {chain}")

    def test_zhipu_precedes_kimi_precedes_copilot_precedes_google(self):
        rank = {fam: i for i, fam in enumerate(FAMILY_ORDER)}
        for tier, chain in self.chains.items():
            ranks = [rank[_family(m)] for m in chain if _family(m) in rank]
            self.assertEqual(ranks, sorted(ranks), f"{tier} violates the priority order: {chain}")

    def test_every_chain_starts_with_zhipu(self):
        for tier, chain in self.chains.items():
            self.assertEqual(_family(chain[0]), "zhipu", f"{tier} must start with zhipu: {chain}")

    def test_opencode_model_is_the_configured_fallback_key(self):
        fallback_keys = {c[-1] for c in self.chains.values()}
        self.assertEqual(fallback_keys, {"opencode-deepseek-v4.1-flash"})


if __name__ == "__main__":
    unittest.main()
