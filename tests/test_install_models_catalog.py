"""A fresh workspace must start on the router, and pi's catalog must follow quota_policy.yaml."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml

import scripts.install_global as installer

POLICY = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"


class SettingsDefaultsTests(unittest.TestCase):
    def test_missing_defaults_point_at_the_router(self) -> None:
        merged = installer.merge_pi_settings({"defaultTools": ["read"]})
        self.assertEqual(merged["defaultProvider"], installer.HARNESS_PROVIDER)
        self.assertEqual(merged["defaultModel"], installer.DEFAULT_PROVIDER_MODEL)

    def test_an_explicit_choice_is_never_overwritten(self) -> None:
        merged = installer.merge_pi_settings({"defaultProvider": "anthropic", "defaultModel": "claude-x"})
        self.assertEqual(merged["defaultProvider"], "anthropic")
        self.assertEqual(merged["defaultModel"], "claude-x")


class ModelCatalogTests(unittest.TestCase):
    def test_every_policy_model_reaches_pis_catalog(self) -> None:
        policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))["models"]
        router = installer.merge_models_json({}, POLICY)["providers"][installer.HARNESS_PROVIDER]
        self.assertEqual([m["id"] for m in router["models"]], list(policy))
        self.assertEqual(router["baseUrl"], "http://127.0.0.1:8787/v1")

    def test_other_providers_survive_and_stale_entries_go(self) -> None:
        existing = {"providers": {"mine": {"baseUrl": "http://x"},
                                  installer.HARNESS_PROVIDER: {"apiKey": "old", "models": [{"id": "stale"}]}}}
        merged = installer.merge_models_json(existing, POLICY)
        self.assertEqual(merged["providers"]["mine"], {"baseUrl": "http://x"})
        catalog = merged["providers"][installer.HARNESS_PROVIDER]
        self.assertEqual(catalog["apiKey"], "local-harness-proxy")
        self.assertNotIn("stale", [m["id"] for m in catalog["models"]])


if __name__ == "__main__":
    unittest.main()
