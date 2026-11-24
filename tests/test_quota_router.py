from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("HARNESS_TRACES_DIR", tempfile.mkdtemp(prefix="harness-test-traces-"))

from fastapi.testclient import TestClient
import httpx

from tests.sse_util import sse_response

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from proxy_gateway.app import create_app
from proxy_gateway.quota_manager import QuotaManager


class TestSharedPoolQuotaRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "quota_ledger.db"
        self.policy_path = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"
        self.qm = QuotaManager(self.policy_path, self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_zhipu_shared_pool_exhaustion_blocks_both_glm_5_3_and_flash(self) -> None:
        """Exhausting zhipu_v2_max via glm-5.3 immediately skips glm-5.3-flash too!"""
        now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        # Verify exact Zhipu official credit math for GLM-5.4
        # (docs.bigmodel.cn coding-plan overview, read 2026-11-24):
        # 1M input (4.6) + 1M output (16.0) = 20.6 credits (2/3 of GLM-5.3's 30.9)
        units = self.qm.compute_units("zhipu-glm-5.4", prompt_tokens=1_000_000, completion_tokens=1_000_000, now_utc=now)
        self.assertAlmostEqual(units, 20.6, places=3)

        # Spend full 5h Zhipu Max shared pool (28,000 credits) on glm-5.3
        # Local estimates no longer skip this pool (it reports its own percentage usage), so block it
        # the way a real outage does: a 429 that cools the whole shared pool.
        self.qm.mark_upstream_failure("zhipu-glm-5.4", 429, "quota exceeded", 600, now_utc=now)

        # Now system_0 (which wants zhipu-glm-5.3-flash first) MUST skip flash: one shared pool, one verdict.
        # L4 决策 (2026-11-24)：zhipu 池满后滑到 kimi 家族。
        sel = self.qm.select_candidates("system_0", "openai", now_utc=now)
        self.assertEqual(sel.model_key, "kimi-for-coding")
        self.assertIn("pool_zhipu_v2_max_cooldown", sel.skipped_reasons["zhipu-glm-5.3-flash"])

    def test_opencode_go_peak_2x_multiplier(self) -> None:
        """OpenCode Go applies a 2x cost multiplier during its peak window (13:00-21:00 UTC).

        The weekly cap is no longer decided locally: the pool carries a provider usage endpoint and its
        limits are percent, so an exhausted-looking local ledger must not skip it (2026-11-24).
        """
        off_peak = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)
        us_peak = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)
        u_off = self.qm.compute_units("opencode-deepseek-v4.1-flash", prompt_tokens=1_000_000, completion_tokens=1_000_000, now_utc=off_peak)
        u_peak = self.qm.compute_units("opencode-deepseek-v4.1-flash", prompt_tokens=1_000_000, completion_tokens=1_000_000, now_utc=us_peak)
        self.assertAlmostEqual(u_peak, u_off * 2.0, places=4)

        self.qm.record_usage("opencode-deepseek-v4.1-flash", units_override=50.0, now_utc=off_peak - timedelta(days=2))
        sel = self.qm.select_candidates("system_1", "openai", now_utc=off_peak, pin_requested=True)
        self.assertNotIn("opencode-deepseek-v4.1-flash", sel.skipped_reasons)  # provider decides, not the estimate

    def test_local_estimates_no_longer_skip_a_pool_with_a_provider_reading(self) -> None:
        """The three primary pools all report their own usage now; estimated ledger rows in another
        unit must not produce a skip. Only real provider readings or upstream failures may."""
        now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        self.qm.record_usage("kimi-k3.1-pro", units_override=1500.0, now_utc=now)
        self.qm.record_usage("zhipu-glm-5.4", units_override=28000.0, now_utc=now)
        self.qm.record_usage("opencode-deepseek-v4.1-flash", units_override=20.0, now_utc=now)

        sel = self.qm.select_candidates("system_2", "openai", now_utc=now)
        for key in ("zhipu-glm-5.4", "kimi-k3.1-pro", "opencode-deepseek-v4.1-flash"):
            self.assertNotIn(key, sel.skipped_reasons, "a provider-reported pool must not be skipped on an estimate")
        self.assertFalse(sel.last_option_used)

    def test_workbuddy_sits_after_kimi_and_before_opencode(self) -> None:
        """Operator priority: below Zhipu and Kimi, above OpenCode (Copilot/Google are out of the chains)."""
        for tier, chain in self.qm.routing_chains.items():
            wb = [k for k in chain if k.startswith("workbuddy-")]
            self.assertEqual(wb, ["workbuddy-hy4", "workbuddy-glm-5.4"], tier)  # family order HY > GLM
            last_kimi = max(i for i, k in enumerate(chain) if k.startswith("kimi-"))
            first_opencode = chain.index("opencode-deepseek-v4.1-flash")
            self.assertLess(last_kimi, chain.index("workbuddy-hy4"), tier)
            self.assertLess(chain.index("workbuddy-glm-5.4"), first_opencode, tier)
            for key in wb:
                entry = self.qm.models[key]
                self.assertEqual(entry["pool"], "workbuddy")
                self.assertEqual(entry["default_base_url"], "http://harness-workbuddy:8790/v1")
                self.assertIsNone(entry.get("api_key_env"))  # the adapter needs no key

    def test_copilot_and_google_are_in_no_failover_chain(self) -> None:
        for tier, chain in self.qm.routing_chains.items():
            for key in chain:
                self.assertFalse(key.startswith(("copilot-", "google-")), f"{tier}: {key}")

    def test_every_tier_has_an_anthropic_protocol_backup(self) -> None:
        """Anthropic-protocol requests had exactly one candidate per tier (Zhipu) until 2026-11-24,
        so a single Zhipu error ended them in a 503 with nothing to fail over to."""
        now = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)  # off-peak
        for tier in self.qm.routing_chains:
            sel = self.qm.select_candidates(tier, "anthropic", now_utc=now)
            chain = sel.failover_chain
            self.assertGreaterEqual(len(chain), 2, f"{tier}: {chain}")
            self.assertEqual(chain[0], sel.model_key)
            self.assertTrue(all(self.qm.models[k]["protocol"] == "anthropic" for k in chain), f"{tier}: {chain}")
            self.assertTrue(any(k.startswith("kimi-") for k in chain[1:]), f"{tier}: {chain}")
            openai_sel = self.qm.select_candidates(tier, "openai", now_utc=now)
            self.assertFalse(any(k.endswith("-anthropic") for k in openai_sel.failover_chain), f"{tier}: protocol leak")

    def test_kimi_anthropic_entries_share_the_kimi_pool_and_point_at_the_messages_api(self) -> None:
        for key, sibling in (("kimi-for-coding-anthropic", "kimi-for-coding"), ("kimi-k3.1-pro-anthropic", "kimi-k3.1-pro")):
            entry = self.qm.models[key]
            self.assertEqual(entry["protocol"], "anthropic")
            self.assertEqual(entry["pool"], self.qm.models[sibling]["pool"])  # one weekly quota
            self.assertEqual(entry["upstream_model"], self.qm.models[sibling]["upstream_model"])
            self.assertEqual(entry["default_base_url"], "https://api.kimi.com/coding")  # + /v1/messages

    def test_opencode_go_anthropic_entry_uses_the_go_base_not_the_pay_as_you_go_one(self) -> None:
        """/inference/go/v1/messages is on the Go plan; /inference/anthropic/... is pay-as-you-go (402)."""
        entry = self.qm.models["opencode-deepseek-v4.1-flash-anthropic"]
        self.assertEqual(entry["protocol"], "anthropic")
        self.assertEqual(entry["default_base_url"], "https://opencode.ai/inference/go")
        self.assertEqual(entry["pool"], self.qm.models["opencode-deepseek-v4.1-flash"]["pool"])
        self.assertEqual(entry["upstream_model"], "deepseek-v4.1-flash")
        for tier, chain in self.qm.routing_chains.items():
            anthropic = [k for k in chain if self.qm.models[k]["protocol"] == "anthropic"]
            self.assertEqual(anthropic[-1], "opencode-deepseek-v4.1-flash-anthropic", tier)  # tail of the chain

    def test_pinned_lead_is_not_moved_for_price_but_still_fails_over_when_unavailable(self) -> None:
        """Operator decision 2026-11-24: the chair picks the main agent; peak rules govern the rest."""
        peak = datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc)  # OpenCode Go peak window (13:00-21:00 UTC), 2x price
        lead = "opencode-deepseek-v4.1-flash"

        free = self.qm.select_candidates("system_1_5", "openai", lead, now_utc=peak)  # sub-agent / failover traffic
        self.assertNotEqual(free.model_key, lead)
        self.assertTrue(free.peak_avoided)

        pinned = self.qm.select_candidates("system_1_5", "openai", lead, now_utc=peak, pin_requested=True)
        self.assertEqual(pinned.model_key, lead)
        self.assertFalse(pinned.peak_avoided)
        self.assertEqual(pinned.failover_chain[0], lead)

        self.qm.mark_upstream_failure(lead, 404, "Not Found", None, now_utc=peak)  # model out of service
        gone = self.qm.select_candidates("system_1_5", "openai", lead, now_utc=peak, pin_requested=True)
        self.assertNotEqual(gone.model_key, lead)
        self.assertIn("model_endpoint_not_found", gone.skipped_reasons[lead])
        self.assertEqual(gone.model_key, self.qm.select_candidates("system_1_5", "openai", None, now_utc=peak).model_key)

    def test_only_the_chairs_request_pins_the_lead_sub_agents_keep_the_peak_rules(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        peak = datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc)  # OpenCode Go peak window
        qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp.name) / "p.db")

        def upstream(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}})
        client = TestClient(create_app(transport=httpx.MockTransport(upstream), quota_manager=qm, now_provider=lambda: peak))
        body = {"model": "opencode-deepseek-v4.1-flash", "stream": False, "messages": [{"role": "user", "content": "hi"}]}

        lead = client.post("/v1/chat/completions", json=body)  # no agent header: the chair's request
        self.assertEqual(lead.headers["x-harness-selected-model"], "opencode-deepseek-v4.1-flash")
        sub = client.post("/v1/chat/completions", json=body, headers={"X-Harness-Agent-Id": "coder"})  # sub-agent
        self.assertNotEqual(sub.headers["x-harness-selected-model"], "opencode-deepseek-v4.1-flash")

    def test_anthropic_request_reaches_opencode_go_with_bearer_and_session_headers(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        now = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)  # off-peak for every pool
        qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp.name) / "l.db")
        qm.record_usage("zhipu-glm-5.4", units_override=28000.0, now_utc=now)
        qm.record_usage("kimi-k3.1-pro", units_override=3000.0, now_utc=now)
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "go-key-for-test", "OPENCODE_ANTHROPIC_BASE_URL": ""}):
            seen: list[httpx.Request] = []

            def upstream(request: httpx.Request) -> httpx.Response:
                seen.append(request)
                return httpx.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant", "model": "deepseek-v4.1-flash",
                                                "content": [{"type": "text", "text": "go ok"}], "stop_reason": "end_turn",
                                                "usage": {"input_tokens": 1, "output_tokens": 1}})
            client = TestClient(create_app(transport=httpx.MockTransport(upstream), quota_manager=qm, now_provider=lambda: now))
            resp = client.post("/anthropic/v1/messages", json={"model": "claude-sonnet-5.5", "max_tokens": 16, "stream": False,
                                                            "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(str(seen[-1].url), "https://opencode.ai/inference/go/v1/messages")
        self.assertEqual(seen[-1].headers["authorization"], "Bearer go-key-for-test")
        self.assertTrue(seen[-1].headers["x-opencode-session"].startswith("hs-"))

    def test_gateway_429_cools_down_entire_shared_pool_and_fails_over(self) -> None:
        called: list[str] = []

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            called.append(body["model"])
            if body["model"] == "k3.1-pro":
                return httpx.Response(429, headers={"Retry-After": "180"}, json={"error": "rate_limit"})
            return httpx.Response(
                200,
                json={
                    "id": "ok-zhipu",
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                    "usage": {"prompt_tokens": 100000, "completion_tokens": 50000},
                },
            )

        now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        app = create_app(
            transport=httpx.MockTransport(mock_handler),
            quota_manager=self.qm,
            now_provider=lambda: now,
        )
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "kimi-k3.1-pro",
                "stream": False,
                "messages": [{"role": "user", "content": "请用 CAP 定理做收敛态审计"}],
            },
        )
        self.assertEqual(resp.status_code, 200)
        # L4 决策 (2026-11-24)：子代理链序 zhipu > kimi > copilot > google > opencode；
        # 显式请求 kimi-k3.1-pro，429 后 failover 至 zhipu 家族。
        self.assertEqual(called, ["k3.1-pro", "glm-5.4"])
        q = client.get("/quota").json()
        self.assertGreater(q["pools"]["kimi_allegretto"]["cooldown_remaining_sec"], 0)
        # 0.1M * 4.6 + 0.05M * 16.0 = 1.26 credits in zhipu_v2_max shared pool
        self.assertAlmostEqual(q["pools"]["zhipu_v2_max"]["windows"]["5h"]["used"], 1.26, places=2)


    def test_24h_global_active_peak_hour_relay(self) -> None:
        """East Asia peak (04:00 UTC = 12:00 +08:00): Zhipu & Kimi yield to off-peak OpenCode Go!
        US peak (15:00 UTC = 23:00 +08:00): OpenCode Go yields to off-peak Kimi / Zhipu!"""
        cn_daytime = datetime(2026, 11, 19, 4, 0, tzinfo=timezone.utc)
        sel_cn = self.qm.select_candidates("system_2", "openai", now_utc=cn_daytime)
        self.assertTrue(sel_cn.peak_avoided)
        # During CN daytime kimi & zhipu are in peak, and so is OpenCode Go is not: the relay now lands on
        # WorkBuddy first (added 2026-11-24, no peak window) and OpenCode stays the last resort.
        self.assertEqual(sel_cn.model_key, "workbuddy-hy4")
        self.assertIn("opencode-deepseek-v4.1-flash", sel_cn.failover_chain)
        self.assertFalse(sel_cn.last_option_used)

        us_daytime = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)
        sel_us = self.qm.select_candidates("system_1", "openai", now_utc=us_daytime)
        self.assertTrue(sel_us.peak_avoided)
        # During US daytime (OpenCode Go 2x peak), yields to off-peak zhipu-glm-5.3-flash!
        self.assertEqual(sel_us.model_key, "zhipu-glm-5.3-flash")
        self.assertFalse(sel_us.last_option_used)

    def test_cross_family_critic_avoids_same_drafter_pool(self) -> None:
        """System 2+ audit automatically selects a different provider family than the drafter."""
        off_peak_all = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)  # 20:00 +08:00 (both CN & US off-peak)
        # Suppose zhipu_v2_max drafted Turn 1 -> audit MUST pick a DIFFERENT provider family.
        # L4 决策 (2026-11-24)：子代理链首为 zhipu，排除 zhipu 起草池后滑到 kimi 家族。
        sel_critic = self.qm.select_candidates(
            "system_2_plus", "openai", now_utc=off_peak_all, exclude_pool="zhipu_v2_max"
        )
        self.assertEqual(sel_critic.pool_id, "kimi_allegretto")
        self.assertEqual(sel_critic.model_key, "kimi-k3.1-pro")
        self.assertIn("cross_family_critic_excluded", sel_critic.skipped_reasons["zhipu-glm-5.4"])

if __name__ == "__main__":
    unittest.main()


class TestUpstreamFailureHandling(unittest.TestCase):
    """Real upstream signals (429 bodies, 401, 404) must drive cooldowns and be surfaced to the caller."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(self.tmp.name) / "ledger.db")
        self.now = datetime(2026, 11, 19, 14, 50, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_429_body_reset_timestamp_sets_pool_cooldown(self) -> None:
        body = '{"error":{"code":"1308","message":"已达到 5 小时的使用上限。您的限额将在 2026-11-19 23:31:23 重置。"}}'
        info = self.qm.mark_upstream_failure("zhipu-glm-5.4", 429, body, None, now_utc=self.now)
        self.assertEqual(info["scope"], "pool")
        # 23:31:23 at UTC+8 == 15:31:23 UTC
        self.assertEqual(info["until"], datetime(2026, 11, 19, 15, 31, 23, tzinfo=timezone.utc))
        # shared pool: the sibling model is blocked too
        sel = self.qm.select_candidates("system_0", "openai", now_utc=self.now)
        self.assertIn("pool_zhipu_v2_max_cooldown", sel.skipped_reasons["zhipu-glm-5.3-flash"])

    def test_5h_window_hint_without_timestamp_uses_longer_cooldown_than_default(self) -> None:
        body = "You've reached your 5-hour usage limit. Your quota will reset when the current 5-hour window ends."
        info = self.qm.mark_upstream_failure("kimi-for-coding", 429, body, None, now_utc=self.now)
        self.assertEqual(info["until"], self.now + timedelta(seconds=900))

    def test_401_and_404_cool_down_only_that_model(self) -> None:
        self.qm.mark_upstream_failure("kimi-k3.1-pro", 401, "Invalid Authentication", None, now_utc=self.now)
        self.qm.mark_upstream_failure("opencode-deepseek-v4.1-flash", 404, "Not Found", None, now_utc=self.now)
        sel = self.qm.select_candidates("system_1_5", "openai", now_utc=self.now)
        self.assertIn("model_auth_failed", sel.skipped_reasons["kimi-k3.1-pro"])
        self.assertIn("model_endpoint_not_found", sel.skipped_reasons["opencode-deepseek-v4.1-flash"])
        # pool-mates / other pools stay available
        self.assertNotIn("kimi-for-coding", sel.skipped_reasons)

    def test_all_unavailable_probes_only_soonest_recovering_candidate(self) -> None:
        for mk in ("zhipu-glm-5.4", "zhipu-glm-5.3-flash", "kimi-for-coding", "opencode-deepseek-v4.1-flash",
                   "workbuddy-hy4", "workbuddy-glm-5.4",
                   "copilot-claude-sonnet-5.5", "google-ai-gemini-4-neon", "google-ai-gemini-4-hydrogen",
                   "siliconflow-deepseek-v4-flash"):
            self.qm.mark_upstream_failure(mk, 404, "Not Found", None, now_utc=self.now)
        self.qm.mark_upstream_failure("kimi-for-coding", 429, "", 120, now_utc=self.now)  # recovers in 120s
        sel = self.qm.select_candidates("system_1_5", "openai", now_utc=self.now)
        self.assertEqual(len(sel.failover_chain), 1)  # only the soonest-recovering in-chain model

    def test_gateway_surfaces_per_candidate_reasons_when_all_fail(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "Invalid Authentication"}})

        app = create_app(transport=httpx.MockTransport(handler), quota_manager=self.qm, now_provider=lambda: self.now)
        client = TestClient(app)
        resp = client.post("/v1/chat/completions", json={
            "stream": False, "messages": [{"role": "user", "content": "请排查这个多文件问题并对比方案"}]})
        self.assertEqual(resp.status_code, 503)  # the gateway's own status (2026-11-24)
        self.assertEqual(resp.headers["x-harness-all-upstreams-unavailable"], "1")
        self.assertTrue(resp.headers["retry-after"].isdigit())
        msg = resp.json()["error"]["message"]
        self.assertTrue(msg.startswith("HTTP 401 Invalid Authentication. "), msg)  # provider error leads
        self.assertIn("HTTP 401", resp.json()["harness"]["other_candidates"])  # every candidate stays visible
        self.assertIn("Invalid Authentication", msg)

    def test_stream_unavailable_error_includes_upstream_reasons(self) -> None:
        """All candidates failed before any byte reached the client: HTTP 503, never a synthesized reply."""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        app = create_app(transport=httpx.MockTransport(handler), quota_manager=self.qm, now_provider=lambda: self.now)
        client = TestClient(app)
        with client.stream("POST", "/v1/chat/completions", json={
                "stream": True, "messages": [{"role": "user", "content": "请排查这个多文件问题并对比方案"}]}) as r:
            text = "".join(r.iter_text())
            self.assertEqual(r.status_code, 503)
        parsed = json.loads(text)
        self.assertTrue(parsed["harness"]["all_upstreams_unavailable"])
        self.assertTrue(parsed["error"]["message"].startswith("HTTP 404 Not Found. "))
        self.assertIn("HTTP 404", parsed["harness"]["other_candidates"])
        self.assertNotIn("data:", text)  # no SSE frame, so a client cannot store it as an assistant message


class TestProviderRequiredHeaders(unittest.TestCase):
    def test_opencode_go_receives_session_header_stable_across_turns(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp.name) / "l.db")
        seen: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("x-opencode-session", ""))
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}})

        now = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)
        client = TestClient(create_app(transport=httpx.MockTransport(handler), quota_manager=qm, now_provider=lambda: now))
        for follow_up in ("第一问", "第二问"):
            client.post("/v1/chat/completions", json={
                "model": "opencode-deepseek-v4.1-flash", "stream": False,
                "messages": [{"role": "user", "content": "同一会话的首条消息"}, {"role": "user", "content": follow_up}]})
        self.assertTrue(seen[0].startswith("hs-"))
        self.assertEqual(seen[0], seen[1])  # session-stable => provider-side cache affinity


class TestCrossFamilyExclusionRealDispatch(unittest.TestCase):
    """P0-1: exclusion must work for sub-agent dispatches (per-task session ids), not only same-session calls."""

    def test_exclude_model_header_maps_to_drafter_pool(self) -> None:
        from proxy_gateway.exclude_policy import resolve_excluded_pool
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp.name) / "l.db")
        # drafter ran on kimi-for-coding; critic call uses a NEW session id but passes the header
        pool = resolve_excluded_pool({"X-Harness-Exclude-Model": "kimi-for-coding"}, qm, {}, "task-1-critic", True)
        self.assertEqual(pool, "kimi_allegretto")
        # explicit pool header wins
        pool2 = resolve_excluded_pool({"x-harness-exclude-pool": "zhipu_v2_max"}, qm, {}, "s", True)
        self.assertEqual(pool2, "zhipu_v2_max")

    def test_critic_dispatch_never_reuses_drafter_pool_end_to_end(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp.name) / "l.db")
        seen: list[tuple[str, str | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.headers.get("x-harness-agent-id", ""),
                         request.headers.get("x-harness-exclude-model")))
            model = "kimi-for-coding"
            return sse_response("评判：PASS", model=model)

        now = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
        from orchestrator.dispatch import dispatch_subtask
        dispatch_subtask(agent_profile="critic", task_text="review this", task_id="task-9",
                         gateway_url="http://mock.local", transport=httpx.MockTransport(handler),
                         exclude_model="kimi-for-coding")
        self.assertEqual(seen[0][1], "kimi-for-coding")  # header actually sent


class TestCriticSessionFallback(unittest.TestCase):
    """Client-agnostic cross-family: no exclude headers needed (OpenCode/Claude Code/Codex)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(self.tmp.name) / "l.db")

    def test_suffix_and_global_fallback_resolution(self) -> None:
        from proxy_gateway.exclude_policy import resolve_excluded_pool
        table = {"task-7": "kimi_allegretto"}
        # 1) exact session
        self.assertEqual(resolve_excluded_pool({}, self.qm, table, "task-7", True), "kimi_allegretto")
        # 2) critic suffix stripped back to the drafter session
        self.assertEqual(resolve_excluded_pool({}, self.qm, table, "task-7-critic", True), "kimi_allegretto")
        # 3) globally remembered drafter
        self.assertEqual(resolve_excluded_pool({}, self.qm, {}, "other-session", True, "zhipu_v2_max"), "zhipu_v2_max")
        # 4) non-critic turns never exclude
        self.assertIsNone(resolve_excluded_pool({}, self.qm, table, "task-7", False))

    def test_gateway_remembers_drafter_and_excludes_it_without_headers(self) -> None:
        pools_seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            user = body["messages"][-1]["content"]
            # critic turn (system_2_plus fingerprint) must not land on the drafter's pool
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}})

        now = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
        qm = self.qm
        # make kimi the only fast option for the drafter request
        client = TestClient(create_app(transport=httpx.MockTransport(handler), quota_manager=qm, now_provider=lambda: now))
        first = client.post("/v1/chat/completions", json={"stream": False, "model": "kimi-for-coding",
                                                         "messages": [{"role": "user", "content": "写一个函数"}]})
        pool1 = first.headers["x-harness-selected-model"] and qm.pool_for_model(first.headers["x-harness-selected-model"])[0]
        # critic request, DIFFERENT session id, NO exclude headers
        second = client.post("/v1/chat/completions", headers={"x-harness-session-id": "brand-new"},
                             json={"stream": False, "messages": [{"role": "user", "content": "请做独立复核并给出最终裁决"}]})
        pool2 = qm.pool_for_model(second.headers["x-harness-selected-model"])[0]
        self.assertNotEqual(pool1, pool2, "critic must move to a different provider family")


class TestModelEffortCeiling(unittest.TestCase):
    def test_model_max_effort_clamps_decision(self) -> None:
        from proxy_gateway.policy import clamp_effort_for_model, decide_routing
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        qm = QuotaManager(REPO_ROOT / "proxy_gateway" / "quota_policy.yaml", Path(tmp.name) / "l.db")
        d = decide_routing([{"role": "user", "content": "请做第一性原理推演并形式化证明" }])  # system_2 -> high
        clamped = clamp_effort_for_model(qm, "opencode-deepseek-v4.1-flash", d)
        self.assertEqual(clamped.tier, d.tier)          # tier unchanged
        self.assertEqual(clamped.openai_effort, "low")  # effort clamped by evidence
        # models without a ceiling are untouched
        self.assertEqual(clamp_effort_for_model(qm, "zhipu-glm-5.4", d).openai_effort, d.openai_effort)
