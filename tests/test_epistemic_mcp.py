import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from mcp_server.dag_engine import EpistemicEngine


class TestEpistemicHardConstraints(unittest.TestCase):
    def setUp(self) -> None:
        # Persisted L4/L5 memory must not land in the repo's real store during tests.
        self._store = tempfile.TemporaryDirectory()
        self.engine = EpistemicEngine(REPO_ROOT, store_root=Path(self._store.name))

    def tearDown(self) -> None:
        self._store.cleanup()

    def test_f04_blocks_invented_l1_axiom(self) -> None:
        """F-04: Model cannot invent L1 axioms outside read-only l1_axioms/."""
        with self.assertRaises(ValueError) as ctx:
            self.engine.submit_l5_claim({
                "claim_id": "L5-BAD-01",
                "claim": "UNIX 哲学要求绝不污染 stdout",
                "claimed_tier": "L1",
                "source_ids": ["L1-UNIX-PHILOSOPHY"],
            })
        self.assertIn("L1_CREEP_BLOCKED", str(ctx.exception))

    def test_f01_transitive_weakest_link_override(self) -> None:
        """F-01 / TC-02: Multi-hop L3 -> L5-1 -> L5-2 must be hard-capped at L3."""
        r1 = self.engine.submit_l5_claim({
            "claim_id": "L5-TRIAL-01",
            "claim": "缩短到 7 天试用需把销售跟进压缩到前 48 小时",
            "claimed_tier": "L2",
            "source_ids": ["L3-PLG-001"],
        })
        self.assertEqual(r1["effective_tier"], "L3")
        self.assertTrue(r1["downgraded"])

        # Turn 2 tries to launder L5-TRIAL-01 into an L1 CEO conclusion
        r2 = self.engine.submit_l5_claim({
            "claim_id": "L5-CEO-02",
            "claim": "缩短到 7 天必然提升 30% 转化并上调 ARR",
            "claimed_tier": "L1",
            "source_ids": ["L5-TRIAL-01", "L1-FIN-001"],
        })
        self.assertEqual(r2["effective_tier"], "L3")
        self.assertTrue(r2["downgraded"])
        self.assertIn("WEAKEST_LINK_OVERRIDE", r2["downgrade_reason"])

    def test_pure_l1_derivation_stays_l1(self) -> None:
        """TC-03: Pure L1 CAP theorem proof must stay L1 without false downgrade."""
        self.engine.register_l4_input("L4-LEDGER-01", "分区期间同时 100% 强一致与 100% 写入可用")
        res = self.engine.submit_l5_claim({
            "claim_id": "L5-CAP-PROOF",
            "claim": "跨机房分区期间无法同时满足 100% 强一致与 100% 写入可用",
            "claimed_tier": "L1",
            "source_ids": ["L1-CAP-001", "L4-LEDGER-01"],
            "conflicts_with_l1": ["L1-CAP-001"],
        })
        self.assertEqual(res["effective_tier"], "L1")
        self.assertFalse(res["downgraded"])
        self.assertEqual(res["status"], "blocked_l1_conflict")

        audit = self.engine.audit_dag()
        self.assertFalse(audit["converge_allowed"])
        self.assertEqual(audit["blocked_l1_conflicts"], ["L5-CAP-PROOF"])

    def test_l3_recall_always_contains_counter_examples(self) -> None:
        res = self.engine.recall_l3("微服务")
        self.assertTrue(res["falsifiable"])
        self.assertGreaterEqual(len(res["items"]), 1)
        for item in res["items"]:
            self.assertTrue(item["scope_conditions"])
            self.assertTrue(item["counter_examples"])

    def test_promotion_gate_queues_pr_without_mutating_l1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.engine.promotions_dir = Path(tmp)
            pr = self.engine.propose_promotion(
                "L3-ARCH-002", "L2", "已完成 3 个小团队项目实测验证"
            )
            self.assertEqual(pr["queued"]["status"], "awaiting_human_approval")
            self.assertTrue((Path(tmp) / "pending_pr.yaml").exists())

    def test_live_mcp_stdio_jsonrpc_roundtrip(self) -> None:
        """Spawn real mcp_server/server.py over stdio and verify MCP JSON-RPC 2.0."""
        store = tempfile.TemporaryDirectory()
        self.addCleanup(store.cleanup)
        env = {**os.environ, "HARNESS_MEMORY_STORE": store.name}
        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "mcp_server" / "server.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        assert proc.stdin and proc.stdout
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "query_l1", "arguments": {"query": "CAP"}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "submit_l5_claim",
                    "arguments": {
                        "claim_id": "L5-BAD",
                        "claim": "伪造公理测试",
                        "claimed_tier": "L1",
                        "source_ids": ["L1-FAKE-999"],
                    },
                },
            },
        ]
        for r in requests:
            proc.stdin.write(json.dumps(r) + "\n")
        proc.stdin.flush()
        proc.stdin.close()

        lines = [json.loads(line) for line in proc.stdout.read().splitlines() if line.strip()]
        proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
        proc.wait(timeout=5)

        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "epistemic-mcp")
        tool_names = {t["name"] for t in lines[1]["result"]["tools"]}
        self.assertIn("submit_l5_claim", tool_names)
        self.assertFalse(lines[2]["result"]["isError"])
        self.assertIn("L1-CAP-001", lines[2]["result"]["content"][0]["text"])
        self.assertTrue(lines[3]["result"]["isError"])
        self.assertIn("L1_CREEP_BLOCKED", lines[3]["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
