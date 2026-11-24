#!/usr/bin/env python3
"""Phase 2 Local Dual-Protocol LLM Proxy Gateway (Multi-Provider Quota + Peak + Anti-Thrashing)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import uuid
import os
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx

from proxy_gateway.policy import (
    decide_routing,
    rewrite_anthropic_payload,
    inject_thinking_language_anthropic,
    inject_thinking_language_openai,
    rewrite_openai_payload,
    sanitize_openai_payload,
    apply_effort_override,
    _extract_last_user_text,
)
from proxy_gateway.exclude_policy import resolve_excluded_pool
from proxy_gateway.provider_auth import copilot_auth, google_headers
from proxy_gateway.response_guard import (
    build_contract_intercept,
    check_response_contract,
    normalize_declared_cap,
    build_tier_tag,
    detect_mode,
    guard_anthropic_content,
    guard_anthropic_stream_delta,
    guard_openai_message,
    guard_openai_stream_delta,
    StreamTagGuard,
)
from proxy_gateway.quota_manager import QuotaManager
from proxy_gateway.interim_guard import interim_mode, requested_interim_schema, check_interim_response, interim_note, enforce_directive
from proxy_gateway.thrashing_guard import GuardState, RECOVERY_DIRECTIVE

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_FILE = REPO_ROOT / "traces" / "gateway_traces.jsonl"
DEFAULT_QUOTA_POLICY = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"
DEFAULT_QUOTA_DB = REPO_ROOT / "traces" / "quota_ledger.db"


def _contract_check_enabled(request: Request) -> bool:
    """Ablation switch (Paper 3 internal axis): env kills it globally; the
    x-harness-no-contract header kills it per request (arm A runs clean)."""
    if os.getenv("HARNESS_CONTRACT_CHECK", "on").strip().lower() in ("off", "0", "false"):
        return False
    return not request.headers.get("x-harness-no-contract")


def _log_trace(entry: dict[str, Any]) -> None:
    TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _build_upstream_headers(
    req: Request, qm: QuotaManager, model_key: str, protocol: str,
    resolve_body: dict[str, Any] | None = None,
) -> dict[str, str]:
    keep = ("authorization", "x-api-key", "anthropic-version", "anthropic-beta", "content-type")
    hdrs = {k: v for k, v in req.headers.items() if k.lower() in keep}
    mcfg = qm.models.get(model_key, {})
    auth_mode = str(mcfg.get("auth", "")).strip().lower()

    if auth_mode == "copilot":
        # No static key: exchange a GitHub token for a short-lived Copilot token, then fingerprint as VS Code Chat.
        cop = copilot_auth()
        hdrs.update(cop.headers(resolve_body))
        cop_auth = cop.headers(resolve_body).get("Authorization")
        if cop_auth:
            hdrs["authorization"] = cop_auth
    elif auth_mode == "google":
        key = qm.resolve_api_key(model_key)
        if key:
            for name, value in google_headers(key).items():
                hdrs[name.lower()] = value
    else:
        key = qm.resolve_api_key(model_key)
        if key:
            if protocol == "anthropic":
                hdrs["x-api-key"] = key
            else:
                hdrs["authorization"] = f"Bearer {key}"
    # Provider agent-client fingerprint (issue: vendor-agent quotas). Applied
    # AFTER auth so it can override SDK-generic defaults. Enable per model only
    # with a VERIFIED fingerprint — an incorrect one may break auth or violate
    # the provider's ToS (subscription-agent quota is meant for that agent).
    fp = mcfg.get("client_fingerprint") or {}
    if fp.get("user_agent"):
        hdrs["user-agent"] = str(fp["user_agent"])
    for _name, _value in (fp.get("extra_headers") or {}).items():
        hdrs[str(_name).lower()] = str(_value)
    # Per-model provider-required headers (e.g. OpenCode Go demands x-opencode-session for session affinity).
    sid = getattr(req.state, "harness_sid", None) or "default"
    for name, tmpl in (qm.models.get(model_key, {}).get("upstream_headers") or {}).items():
        hdrs[str(name)] = str(tmpl).replace("{session}", sid)
    hdrs.setdefault("content-type", "application/json")
    return hdrs


def _resolve_base(qm: QuotaManager, model_key: str, fallback: str) -> str:
    """Provider adapters may own the upstream host (e.g. Copilot proxy-ep from the token)."""
    mcfg = qm.models.get(model_key, {})
    if str(mcfg.get("auth", "")).strip().lower() == "copilot":
        derived = copilot_auth().base_url()
        if derived:
            return derived.rstrip("/")
    return qm.resolve_upstream_url(model_key, fallback)


def _derive_session_id(req: Request, body: dict[str, Any]) -> str:
    """Conversation-stable id: explicit header wins; else hash of the first user message (stable across turns)."""
    explicit = req.headers.get("x-harness-session-id") or req.headers.get("x-session-id")
    if explicit:
        return explicit
    for m in body.get("messages", []) or []:
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            return "hs-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:24]
    return "hs-" + uuid.uuid4().hex[:24]


def _parse_retry_after(resp: httpx.Response) -> int | None:
    val = resp.headers.get("retry-after")
    if val and val.isdigit():
        return int(val)
    return None


def _is_failover_status(code: int) -> bool:
    return code >= 400


async def _record_upstream_failure(
    qm: Any, model_key: str, resp: Any, failures: dict[str, str], now: Any, streaming: bool = False
) -> None:
    """Classify an upstream HTTP failure (cooldown by status class) and keep a sanitized reason."""
    try:
        if streaming:
            await resp.aread()
        body_text = resp.text or ""
    except Exception:  # noqa: BLE001
        body_text = ""
    qm.mark_upstream_failure(model_key, resp.status_code, body_text, _parse_retry_after(resp), now_utc=now)
    failures[model_key] = f"HTTP {resp.status_code}: {' '.join(body_text.split())[:140]}"


def _failure_summary(failures: dict[str, str], skipped: dict[str, str]) -> str:
    parts = [f"{k} -> {v}" for k, v in failures.items()]
    parts += [f"{k} -> skipped({v})" for k, v in skipped.items() if k not in failures and not v.startswith("held_in_last")]
    return "; ".join(parts)[:900] or "no candidate attempted"


def create_app(
    openai_upstream: str | None = None,
    anthropic_upstream: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    quota_manager: QuotaManager | None = None,
    now_provider: Any = None,
) -> FastAPI:
    app = FastAPI(title="Epistemic Harness Proxy Gateway", version="0.3.1")
    oa_fallback = (openai_upstream or os.getenv("UPSTREAM_OPENAI_URL", "https://api.openai.com/v1")).rstrip("/")
    an_fallback = (anthropic_upstream or os.getenv("UPSTREAM_ANTHROPIC_URL", "https://api.anthropic.com")).rstrip("/")
    qm = quota_manager or QuotaManager(DEFAULT_QUOTA_POLICY, DEFAULT_QUOTA_DB)
    get_now = now_provider or (lambda: datetime.now(timezone.utc))
    session_last_pool: dict[str, str] = {}
    drafter_state: dict[str, str | None] = {"last_pool": None}
    thinking_lang_mode = os.getenv("HARNESS_THINKING_LANG", "en_with_native_terms")
    # Long deliberative tiers (system_2+, budget 8192) routinely exceed 120s; make it configurable.
    upstream_timeout = httpx.Timeout(float(os.getenv("HARNESS_UPSTREAM_TIMEOUT_SECONDS", "600")))

    def _openai_contract_chunk(chunk_id: str, text: str) -> str:
        """Inject a corrective content delta before the final [DONE] (no finish_reason)."""
        return "data: " + json.dumps({
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        }) + "\n\n"

    def _openai_terminal_chunk(chunk_id: str, text: str, finish_reason: str = "stop") -> str:
        chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\ndata: [DONE]\n\n"

    def _anthropic_terminal_events(text: str) -> bytes:
        notice = (
            "event: content_block_delta\n"
            + f'data: {{"type":"content_block_delta","index":1,"delta":{{"type":"text_delta","text":{json.dumps(text, ensure_ascii=False)}}}}}\n\n'
            + 'event: message_delta\n'
            + 'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
            + 'event: message_stop\n'
            + 'data: {"type":"message_stop"}\n\n'
        )
        return notice.encode("utf-8")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "models_configured": len(qm.models)}

    @app.get("/version")
    async def version() -> dict[str, Any]:
        """Harness version triangulation, served by the repo that built this
        container — authoritative even when the client's cwd is NOT the
        harness repo (global mode, 2026-11-23)."""
        try:
            import importlib.util
            import sys
            repo_root = Path(__file__).resolve().parent.parent
            script = repo_root / "scripts" / "harness_version.py"
            spec = importlib.util.spec_from_file_location("harness_version_srv", script)
            if spec is None or spec.loader is None:
                return {"status": "error", "error": f"script not found: {script}"}
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            info = mod.collect()
            # effective contract: the session file wins, the repo copy is the
            # fallback (containers / fresh installs have no ~/.pi/agent/AGENTS.md)
            if not info.get("loaded_contract_version"):
                info["loaded_contract_version"] = info.get("repo_contract_version")
            return {"status": "ok", **info}
        except Exception as exc:  # noqa: BLE001 - version must never 500
            return {"status": "error", "error": str(exc)[:200]}

    @app.get("/quota")
    async def quota_status() -> dict[str, Any]:
        return qm.status_snapshot(get_now())

    @app.get("/traces")
    async def list_traces(limit: int = 20) -> dict[str, Any]:
        if not TRACE_FILE.exists():
            return {"traces": []}
        lines = TRACE_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
        return {"traces": [json.loads(line) for line in lines if line.strip()]}

    def _interim_check(request: Request, text: str) -> str | None:
        """Interim-schema guard (P1.5): header opt-in, env mode, warn-note only."""
        if interim_mode() == "off" or not text.strip():
            return None
        schema_name = requested_interim_schema(request.headers.get("x-harness-interim"))
        if not schema_name:
            return None
        ok, violations = check_interim_response(text, schema_name)
        return None if ok else interim_note(schema_name, violations)

    def _resolve_agent(request: Request) -> tuple[str, dict[str, Any] | None]:
        """Resolve X-Harness-Agent-Id to its profile (tier + pinned model)."""
        agent_id = request.headers.get("x-harness-agent-id", "").strip().lower()
        profile = qm.agent_profiles.get(agent_id) if agent_id else None
        return agent_id, profile

    @app.post("/v1/chat/completions")
    async def openai_chat_completions(request: Request) -> Any:
        body = await request.json()
        request.state.harness_sid = _derive_session_id(request, body)
        now = get_now()
        agent_id, profile = _resolve_agent(request)
        agent_tier = str(profile.get("tier", "")).strip().lower() if profile else None
        decision = decide_routing(body.get("messages", []), dict(request.headers), agent_tier=agent_tier)
        decision = apply_effort_override(decision, request.headers.get("x-harness-effort"))
        user_text = _extract_last_user_text(body.get("messages", []))
        tier_tag = build_tier_tag(decision.tier, detect_mode(user_text, decision.tier))
        requested_model = body.get("model")
        if not requested_model and profile and profile.get("model"):
            requested_model = str(profile["model"]).strip()
        sess_id = request.headers.get("x-harness-session-id", "default")
        exclude_pool = resolve_excluded_pool(
            dict(request.headers), qm, session_last_pool, sess_id,
            decision.cross_family_critic, drafter_state["last_pool"],
        )
        selection = qm.select_candidates(
            decision.tier,
            "openai",
            requested_model,
            now_utc=now,
            fallback_base_url=oa_fallback,
            exclude_pool=exclude_pool,
        )
        session_last_pool[sess_id] = selection.pool_id
        if not decision.cross_family_critic:
            drafter_state["last_pool"] = selection.pool_id
        is_stream = bool(body.get("stream", False))
        guard = GuardState(decision.tier, decision.max_thinking_chars, decision.max_pivots)
        chosen_key = selection.model_key

        if not is_stream:
            last_resp: httpx.Response | None = None
            failures: dict[str, str] = {}
            async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as client:
                for mkey in selection.failover_chain:
                    chosen_key = mkey
                    rewritten = inject_thinking_language_openai(rewrite_openai_payload(body, decision), thinking_lang_mode)
                    rewritten["model"] = qm.models[mkey]["upstream_model"]
                    target_base = _resolve_base(qm, mkey, oa_fallback)
                    rewritten = sanitize_openai_payload(rewritten, target_base)
                    resp = await client.post(
                        f"{target_base}/chat/completions",
                        json=rewritten,
                        headers=_build_upstream_headers(request, qm, mkey, "openai", rewritten),
                    )
                    last_resp = resp
                    if _is_failover_status(resp.status_code):
                        await _record_upstream_failure(qm, mkey, resp, failures, now)
                        continue
                    break

            assert last_resp is not None
            if failures and _is_failover_status(last_resp.status_code):
                return JSONResponse(
                    status_code=502,
                    content={"error": {
                        "type": "harness_gateway_error",
                        "message": "[HARNESS_GATEWAY_ERROR] All upstream candidates failed: "
                        + _failure_summary(failures, selection.skipped_reasons),
                    }},
                    headers={"X-Harness-Routed-Tier": decision.tier},
                )
            data = last_resp.json()
            if not isinstance(data, dict):
                data = {"choices": []}
            # raw upstream text BEFORE gateway tag injection: the interim schema
            # polices the model's output, not the harness's own prefix
            _raw_msg = (data.get("choices") or [{}])[0].get("message") or {}
            _raw_text = _raw_msg.get("content") if isinstance(_raw_msg.get("content"), str) else ""
            tag_injected = guard_openai_message(data, tier_tag)

            # Review-turn output-contract check (issue #1): bounce exactly once
            # with a corrective directive; on repeat violation append an L2
            # escalation intercept instead of looping.
            resp_mode = detect_mode(user_text, decision.tier)
            contract_violations: list[str] = []
            _msg = (data.get("choices") or [{}])[0].get("message") or {}
            _resp_text = _msg.get("content") if isinstance(_msg.get("content"), str) else ""
            _interim_note = _interim_check(request, _raw_text)
            if _interim_note and interim_mode() == "enforce":
                # bounce once: retry upstream with a corrective directive, then degrade
                _schema_name = requested_interim_schema(request.headers.get("x-harness-interim"))
                _ok0, _viol0 = check_interim_response(_raw_text, _schema_name)
                _retry = dict(rewritten)
                _rmsgs = list(_retry.get("messages") or [])
                _rmsgs.append({"role": "system", "content": enforce_directive(_schema_name, _viol0)})
                _retry["messages"] = _rmsgs
                try:
                    async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as rclient:
                        rresp = await rclient.post(
                            f"{target_base}/chat/completions",
                            json=_retry,
                            headers=_build_upstream_headers(request, qm, chosen_key, "openai", _retry),
                        )
                    if rresp.status_code < 400:
                        rdata = rresp.json()
                        _rmsg0 = (rdata.get("choices") or [{}])[0].get("message") or {}
                        _rtext0 = _rmsg0.get("content") if isinstance(_rmsg0.get("content"), str) else ""
                        _ok_retry, _ = check_interim_response(_rtext0, _schema_name)
                        if _ok_retry:
                            data = rdata
                            _msg = (data.get("choices") or [{}])[0].get("message") or {}
                            _resp_text = _msg.get("content") if isinstance(_msg.get("content"), str) else ""
                            _interim_note = None
                            tag_injected = guard_openai_message(data, tier_tag)
                except httpx.HTTPError:
                    pass
            if _interim_note and isinstance(_msg.get("content"), str):
                _msg["content"] = f"{_msg['content']}\n\n{_interim_note}"
            if _resp_text:
                # Cap is computed, not self-declared: align the header before judging.
                _resp_text, _cap_note = normalize_declared_cap(_resp_text)
                if _cap_note and isinstance(_msg.get("content"), str):
                    _msg["content"] = _resp_text
                contract_violations = check_response_contract(_resp_text, decision.tier, resp_mode) if _contract_check_enabled(request) else []
            if contract_violations and isinstance(_msg.get("content"), str):
                retry_payload = dict(rewritten)
                _rmsgs = list(retry_payload.get("messages") or [])
                _rmsgs.append({"role": "system", "content": build_contract_intercept(contract_violations, retry=True)})
                retry_payload["messages"] = _rmsgs
                try:
                    async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as rclient:
                        rresp = await rclient.post(
                            f"{target_base}/chat/completions",
                            json=retry_payload,
                            headers=_build_upstream_headers(request, qm, chosen_key, "openai", retry_payload),
                        )
                    if rresp.status_code < 400:
                        rdata = rresp.json()
                        _rmsg = (rdata.get("choices") or [{}])[0].get("message") or {}
                        _rtext = _rmsg.get("content") if isinstance(_rmsg.get("content"), str) else ""
                        _rtext, _cap_note_r = normalize_declared_cap(_rtext)
                        if _cap_note_r:
                            _rmsg["content"] = _rtext
                        _still = (
                            check_response_contract(_rtext, decision.tier, resp_mode)
                            if _contract_check_enabled(request) else []
                        ) if _rtext else list(contract_violations)
                        if _rtext and not _still:
                            data = rdata
                            contract_violations = []
                            tag_injected = guard_openai_message(data, tier_tag)
                except httpx.HTTPError:
                    pass
            if contract_violations:
                _msg2 = (data.get("choices") or [{}])[0].get("message") or {}
                if isinstance(_msg2.get("content"), str):
                    _msg2["content"] = (
                        _msg2["content"] + "\n\n" + build_contract_intercept(contract_violations, retry=False)
                    )

            usage = data.get("usage") or {}
            qm.record_usage(
                chosen_key,
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                now_utc=now,
            )
            last_opt = qm.is_last_option(chosen_key)
            _log_trace({
                "ts": now.isoformat(),
                "protocol": "openai",
                "tier": decision.tier,
                "effort": decision.openai_effort,
                "selected_model": chosen_key,
                "peak_avoided": selection.peak_avoided,
                "last_option_used": last_opt,
                "skipped": selection.skipped_reasons,
                "stream": False,
                "tripped": False,
                "agent_id": agent_id or None,
                "tag_injected": tag_injected,
                "contract_violations": contract_violations or None,
                "interim_violations": _interim_note or None,
            })
            return JSONResponse(
                status_code=last_resp.status_code,
                content=data,
                headers={
                    "X-Harness-Routed-Tier": decision.tier,
                    "X-Harness-Selected-Model": chosen_key,
                    "X-Harness-Effort": decision.openai_effort,
                    "X-Harness-Peak-Avoided": str(selection.peak_avoided).lower(),
                    "X-Harness-Last-Option-Used": str(last_opt).lower(),
                    "X-Harness-Tier-Tag": tier_tag,
                },
            )

        async def sse_proxy() -> AsyncIterator[bytes]:
            nonlocal chosen_key
            out_chars = 0
            tag_done = False
            tag_injected = False
            tripped = False
            completed = False
            last_chunk_id = "harness-fallback"
            openai_tag_guard = StreamTagGuard(tier_tag)
            failures: dict[str, str] = {}
            resp_mode = detect_mode(user_text, decision.tier)
            full_text = ""
            done_line: str | None = None
            contract_violations: list[str] = []
            for mkey in selection.failover_chain:
                chosen_key = mkey
                rewritten = inject_thinking_language_openai(rewrite_openai_payload(body, decision), thinking_lang_mode)
                rewritten["model"] = qm.models[mkey]["upstream_model"]
                target_base = _resolve_base(qm, mkey, oa_fallback)
                rewritten = sanitize_openai_payload(rewritten, target_base)
                saw_done = False
                saw_finish = False
                try:
                    async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as client:
                        async with client.stream(
                            "POST",
                            f"{target_base}/chat/completions",
                            json=rewritten,
                            headers=_build_upstream_headers(request, qm, mkey, "openai", rewritten),
                        ) as resp:
                            if resp.status_code >= 400:
                                await _record_upstream_failure(qm, mkey, resp, failures, now, streaming=True)
                                continue
                            async for raw_line in resp.aiter_lines():
                                if not raw_line:
                                    yield b"\n"
                                    continue
                                if raw_line == "data: [DONE]":
                                    saw_done = True
                                    done_line = raw_line  # held: contract check runs before [DONE]
                                    continue
                                if raw_line.startswith("data: "):
                                    try:
                                        chunk_obj = json.loads(raw_line[6:])
                                        if chunk_obj.get("id"):
                                            last_chunk_id = chunk_obj["id"]
                                        choice = (chunk_obj.get("choices") or [{}])[0]
                                        delta = choice.get("delta") or {}
                                        if choice.get("finish_reason"):
                                            saw_finish = True
                                        if delta.get("content"):
                                            full_text += str(delta["content"])
                                            emitted = openai_tag_guard.feed(str(delta["content"]))
                                            if emitted is not None:
                                                delta["content"] = emitted
                                            tag_injected = openai_tag_guard.injected or tag_injected
                                        out_chars += len(str(delta.get("content") or ""))
                                        thinking = delta.get("reasoning_content") or delta.get("reasoning") or ""
                                        if thinking and guard.feed_thinking(str(thinking)):
                                            tripped = True
                                            break
                                    except json.JSONDecodeError:
                                        pass
                                yield (raw_line + "\n").encode("utf-8")
                except httpx.HTTPError as exc:
                    failures[mkey] = f"transport_error: {type(exc).__name__}"
                    qm.mark_upstream_failure(mkey, 599, str(exc), None, now_utc=now)
                    continue
                if tripped:
                    completed = True
                    break
                if not (saw_done and saw_finish):
                    # Upstream truncated the stream (no finish chunk / no [DONE]):
                    # synthesize terminal frames so clients never see
                    # "Stream ended without finish_reason". The synthesized
                    # frame carries its own [DONE]; the held line is dropped.
                    yield _openai_terminal_chunk(
                        last_chunk_id, "\n\n[HARNESS_GATEWAY] upstream stream terminated without finish_reason; terminal frame synthesized."
                    ).encode("utf-8")
                else:
                    if full_text.strip():
                        # Review-turn contract check (issue #1): inject the
                        # intercept once, before the held [DONE], so the client
                        # sees the bounce. Cap mismatches are normalized
                        # (computed), not bounced — surfaced as a note chunk.
                        cap_notes: list[str] = []
                        contract_violations = (
                            check_response_contract(full_text, decision.tier, resp_mode, notes=cap_notes)
                            if _contract_check_enabled(request) else []
                        )
                        if cap_notes:
                            yield _openai_contract_chunk(
                                last_chunk_id, "\n\n" + cap_notes[0]
                            ).encode("utf-8")
                        _interim_note = _interim_check(request, full_text)
                        if _interim_note:
                            yield _openai_contract_chunk(last_chunk_id, "\n\n" + _interim_note).encode("utf-8")
                        if contract_violations:
                            yield _openai_contract_chunk(
                                last_chunk_id, "\n\n" + build_contract_intercept(contract_violations, retry=True)
                            ).encode("utf-8")
                    if done_line is not None:
                        yield (done_line + "\n").encode("utf-8")
                completed = True
                break
            if tripped:
                # Seamless auto-recovery: restart once with effort='low' + RECOVERY_DIRECTIVE
                # so the client never receives a dead-stop mid-task.
                guard.auto_recovered = True
                rec_payload = dict(rewritten)
                rec_payload["reasoning_effort"] = "low"
                rec_msgs = list(rec_payload.get("messages") or [])
                rec_msgs.append({"role": "system", "content": RECOVERY_DIRECTIVE})
                rec_payload["messages"] = rec_msgs
                rec_done = rec_finish = False
                try:
                    async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as client:
                        async with client.stream(
                            "POST",
                            f"{target_base}/chat/completions",
                            json=rec_payload,
                            headers=_build_upstream_headers(request, qm, chosen_key, "openai", rewritten),
                        ) as rec_resp:
                            if rec_resp.status_code in (429, 529):
                                qm.mark_rate_limited(chosen_key, _parse_retry_after(rec_resp), now_utc=now)
                            elif rec_resp.status_code < 400:
                                async for rec_line in rec_resp.aiter_lines():
                                    if not rec_line:
                                        yield b"\n"
                                        continue
                                    if rec_line == "data: [DONE]":
                                        rec_done = True
                                        yield (rec_line + "\n").encode("utf-8")
                                        continue
                                    if rec_line.startswith("data: "):
                                        try:
                                            rec_obj = json.loads(rec_line[6:])
                                            if rec_obj.get("id"):
                                                last_chunk_id = rec_obj["id"]
                                            rec_choice = (rec_obj.get("choices") or [{}])[0]
                                            rec_delta = rec_choice.get("delta") or {}
                                            if rec_choice.get("finish_reason"):
                                                rec_finish = True
                                            if not tag_done and rec_delta.get("content"):
                                                tag_injected = guard_openai_stream_delta(rec_delta, tier_tag) or tag_injected
                                                tag_done = True
                                            out_chars += len(str(rec_delta.get("content") or ""))
                                        except json.JSONDecodeError:
                                            pass
                                    yield (rec_line + "\n").encode("utf-8")
                except httpx.HTTPError:
                    pass
                if not rec_done or not rec_finish:
                    yield _openai_terminal_chunk(
                        last_chunk_id,
                        "\n\n[HARNESS_GATEWAY] auto-recovery continuation unavailable; "
                        "stop-loss: stop internal debate, verify missing facts via MCP/L2 tools, "
                        "or state the minimal unknown and 1-3 concrete next actions.",
                    ).encode("utf-8")
            if not completed and not tripped:
                yield _openai_terminal_chunk(
                    "harness-gateway-error",
                    "[HARNESS_GATEWAY_ERROR] All upstream candidates failed for this request; stop-loss synthesized. Upstream: "
                    + _failure_summary(failures, selection.skipped_reasons),
                ).encode("utf-8")

            qm.record_usage(
                chosen_key,
                prompt_tokens=max(1, len(json.dumps(body.get("messages", []))) // 3),
                completion_tokens=max(1, out_chars // 3),
                thinking_tokens=max(0, guard.thinking_chars // 3),
                now_utc=now,
            )
            _log_trace({
                "ts": now.isoformat(),
                "protocol": "openai",
                "tier": decision.tier,
                "effort": decision.openai_effort,
                "selected_model": chosen_key,
                "peak_avoided": selection.peak_avoided,
                "last_option_used": selection.last_option_used,
                "stream": True,
                "thinking_chars": guard.thinking_chars,
                "pivot_count": guard.pivot_count,
                "tripped": tripped or guard.tripped,
                "trip_reason": guard.trip_reason,
                "upstream_failures": failures or None,
                "agent_id": agent_id or None,
                "tag_injected": tag_injected,
                "contract_violations": contract_violations or None,
            })

        return StreamingResponse(
            sse_proxy(),
            media_type="text/event-stream",
            headers={
                "X-Harness-Routed-Tier": decision.tier,
                "X-Harness-Effort": decision.openai_effort,
                "X-Harness-Selected-Model": chosen_key,
                "X-Harness-Peak-Avoided": str(selection.peak_avoided).lower(),
                "X-Harness-Last-Option-Used": str(selection.last_option_used).lower(),
                "X-Harness-Tier-Tag": tier_tag,
            },
        )

    @app.post("/anthropic/v1/messages")
    async def anthropic_messages(request: Request) -> Any:
        body = await request.json()
        request.state.harness_sid = _derive_session_id(request, body)
        now = get_now()
        agent_id, profile = _resolve_agent(request)
        agent_tier = str(profile.get("tier", "")).strip().lower() if profile else None
        decision = decide_routing(body.get("messages", []), dict(request.headers), agent_tier=agent_tier)
        decision = apply_effort_override(decision, request.headers.get("x-harness-effort"))
        user_text = _extract_last_user_text(body.get("messages", []))
        tier_tag = build_tier_tag(decision.tier, detect_mode(user_text, decision.tier))
        requested_model = body.get("model")
        if not requested_model and profile and profile.get("model"):
            requested_model = str(profile["model"]).strip()
        sess_id = request.headers.get("x-harness-session-id", "default")
        exclude_pool = resolve_excluded_pool(
            dict(request.headers), qm, session_last_pool, sess_id,
            decision.cross_family_critic, drafter_state["last_pool"],
        )
        selection = qm.select_candidates(
            decision.tier, "anthropic", requested_model, now_utc=now,
            fallback_base_url=an_fallback, exclude_pool=exclude_pool,
        )
        session_last_pool[sess_id] = selection.pool_id
        if not decision.cross_family_critic:
            drafter_state["last_pool"] = selection.pool_id
        is_stream = bool(body.get("stream", False))
        guard = GuardState(decision.tier, decision.max_thinking_chars, decision.max_pivots)

        chosen_key = selection.model_key
        rewritten = inject_thinking_language_anthropic(rewrite_anthropic_payload(body, decision), thinking_lang_mode)
        rewritten["model"] = selection.upstream_model

        if not is_stream:
            async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as client:
                resp = await client.post(
                    f"{an_fallback}/v1/messages",
                    json=rewritten,
                    headers=_build_upstream_headers(request, qm, chosen_key, "anthropic", rewritten),
                )
            if _is_failover_status(resp.status_code):
                await _record_upstream_failure(qm, chosen_key, resp, {}, now)
            data = resp.json()
            guard_anthropic_content(data, tier_tag)

            # Review-turn output-contract check (issue #1): bounce exactly once.
            resp_mode = detect_mode(user_text, decision.tier)
            contract_violations: list[str] = []
            _blocks = data.get("content") if isinstance(data.get("content"), list) else []
            _resp_text = "".join(
                str(b.get("text")) for b in _blocks
                if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
            )
            if _resp_text:
                # Cap is computed, not self-declared: align the header before judging.
                _resp_text, _cap_note = normalize_declared_cap(_resp_text)
                if _cap_note and isinstance(_msg.get("content"), str):
                    _msg["content"] = _resp_text
                contract_violations = check_response_contract(_resp_text, decision.tier, resp_mode) if _contract_check_enabled(request) else []
            if contract_violations:
                retry_payload = dict(rewritten)
                _existing_sys = retry_payload.get("system")
                _intercept = build_contract_intercept(contract_violations, retry=True)
                retry_payload["system"] = (
                    (_existing_sys + "\n\n" + _intercept)
                    if isinstance(_existing_sys, str) else _intercept
                )
                try:
                    async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as rclient:
                        rresp = await rclient.post(
                            f"{an_fallback}/v1/messages",
                            json=retry_payload,
                            headers=_build_upstream_headers(request, qm, chosen_key, "anthropic", retry_payload),
                        )
                    if rresp.status_code < 400:
                        rdata = rresp.json()
                        _rblocks = rdata.get("content") if isinstance(rdata.get("content"), list) else []
                        _rtext = "".join(
                            str(b.get("text")) for b in _rblocks
                            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
                        )
                        # Cap is computed, not self-declared: align before judging.
                        _rtext, _cap_note_r2 = normalize_declared_cap(_rtext)
                        if _cap_note_r2:
                            for _b in _rblocks:
                                if isinstance(_b, dict) and _b.get("type") == "text" and isinstance(_b.get("text"), str):
                                    if "Confidence Cap:" in _b["text"]:
                                        _b["text"] = _rtext
                                        break
                        _still = (
                            check_response_contract(_rtext, decision.tier, resp_mode)
                            if _contract_check_enabled(request) else []
                        ) if _rtext else list(contract_violations)
                        if _rtext and not _still:
                            data = rdata
                            contract_violations = []
                            guard_anthropic_content(data, tier_tag)
                except httpx.HTTPError:
                    pass
            if contract_violations:
                _blocks2 = data.get("content")
                if isinstance(_blocks2, list):
                    _blocks2.append({
                        "type": "text",
                        "text": "\n\n" + build_contract_intercept(contract_violations, retry=False),
                    })

            usage = data.get("usage") or {}
            qm.record_usage(
                chosen_key,
                prompt_tokens=int(usage.get("input_tokens", 0)),
                completion_tokens=int(usage.get("output_tokens", 0)),
                now_utc=now,
            )
            return JSONResponse(
                status_code=resp.status_code,
                content=data,
                headers={
                    "X-Harness-Routed-Tier": decision.tier,
                    "X-Harness-Selected-Model": chosen_key,
                    "X-Harness-Tier-Tag": tier_tag,
                },
            )

        async def sse_proxy() -> AsyncIterator[bytes]:
            nonlocal chosen_key
            out_chars = 0
            tag_done = False
            tag_injected = False
            tripped = False
            completed = False
            anthropic_tag_guard = StreamTagGuard(tier_tag)
            failures: dict[str, str] = {}
            resp_mode = detect_mode(user_text, decision.tier)
            full_text = ""
            stop_lines: list[str] = []
            contract_violations: list[str] = []
            for mkey in selection.failover_chain:
                chosen_key = mkey
                rewritten = inject_thinking_language_anthropic(rewrite_anthropic_payload(body, decision), thinking_lang_mode)
                rewritten["model"] = qm.models[mkey]["upstream_model"]
                saw_stop = False
                try:
                    async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as client:
                        async with client.stream(
                            "POST",
                            f"{an_fallback}/v1/messages",
                            json=rewritten,
                            headers=_build_upstream_headers(request, qm, mkey, "anthropic", rewritten),
                        ) as resp:
                            if resp.status_code >= 400:
                                await _record_upstream_failure(qm, mkey, resp, failures, now, streaming=True)
                                continue
                            async for raw_line in resp.aiter_lines():
                                if not raw_line:
                                    yield b"\n"
                                    continue
                                if raw_line.startswith("event: ") and raw_line.strip() == "event: message_stop":
                                    stop_lines = [raw_line]  # held: contract check runs before stop
                                    continue
                                if raw_line.startswith("data: "):
                                    try:
                                        ev = json.loads(raw_line[6:])
                                        if ev.get("type") == "message_stop":
                                            saw_stop = True
                                            stop_lines.append(raw_line)
                                            continue
                                        delta = ev.get("delta") or {}
                                        if delta.get("type") == "text_delta":
                                            text = str(delta.get("text", ""))
                                            full_text += text
                                            out_chars += len(text)
                                            if text:
                                                emitted = anthropic_tag_guard.feed(text)
                                                if emitted is not None:
                                                    delta["text"] = emitted
                                                tag_injected = anthropic_tag_guard.injected or tag_injected
                                        elif delta.get("type") == "thinking_delta":
                                            thinking = str(delta.get("thinking", ""))
                                            if thinking and guard.feed_thinking(thinking):
                                                tripped = True
                                                break
                                    except json.JSONDecodeError:
                                        pass
                                yield (raw_line + "\n").encode("utf-8")
                except httpx.HTTPError as exc:
                    failures[mkey] = f"transport_error: {type(exc).__name__}"
                    qm.mark_upstream_failure(mkey, 599, str(exc), None, now_utc=now)
                    continue
                if tripped:
                    completed = True
                    break
                if not saw_stop:
                    yield _anthropic_terminal_events(
                        "[HARNESS_GATEWAY] upstream stream terminated without message_stop; terminal frame synthesized."
                    )
                if stop_lines and full_text.strip():
                    # Review-turn contract check (issue #1): inject the intercept
                    # once, before the held message_stop. Cap mismatches are
                    # normalized (computed), not bounced — surfaced as a note.
                    cap_notes = []
                    contract_violations = (
                        check_response_contract(
                            full_text, decision.tier, resp_mode, notes=cap_notes)
                        if _contract_check_enabled(request) else []
                    )
                    if cap_notes:
                        yield (
                            "event: content_block_delta\n"
                            + "data: " + json.dumps({
                                "type": "content_block_delta",
                                "delta": {"type": "text_delta", "text": "\n\n" + cap_notes[0]},
                            })
                            + "\n\n"
                        ).encode("utf-8")
                    if contract_violations:
                        yield (
                            "event: content_block_delta\n"
                            + "data: " + json.dumps({
                                "type": "content_block_delta",
                                "delta": {"type": "text_delta", "text": "\n\n" + build_contract_intercept(contract_violations, retry=True)},
                            })
                            + "\n\n"
                        ).encode("utf-8")
                for _sl in stop_lines:
                    yield (_sl + "\n").encode("utf-8")
                completed = True
                break
            if tripped:
                # Seamless auto-recovery: continue with thinking disabled + RECOVERY_DIRECTIVE.
                guard.auto_recovered = True
                rec_payload = dict(rewritten)
                rec_payload["thinking"] = {"type": "disabled"}
                existing_sys = rec_payload.get("system")
                rec_payload["system"] = (
                    (existing_sys + "\n\n" + RECOVERY_DIRECTIVE)
                    if isinstance(existing_sys, str)
                    else RECOVERY_DIRECTIVE
                )
                rec_stop = False
                try:
                    async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as client:
                        async with client.stream(
                            "POST",
                            f"{an_fallback}/v1/messages",
                            json=rec_payload,
                            headers=_build_upstream_headers(request, qm, chosen_key, "anthropic", rewritten),
                        ) as rec_resp:
                            if rec_resp.status_code in (429, 529):
                                qm.mark_rate_limited(chosen_key, _parse_retry_after(rec_resp), now_utc=now)
                            elif rec_resp.status_code < 400:
                                async for rec_line in rec_resp.aiter_lines():
                                    if not rec_line:
                                        yield b"\n"
                                        continue
                                    if rec_line.startswith("data: "):
                                        try:
                                            rec_ev = json.loads(rec_line[6:])
                                            if rec_ev.get("type") == "message_stop":
                                                rec_stop = True
                                            rec_delta = rec_ev.get("delta") or {}
                                            if rec_delta.get("type") == "text_delta":
                                                out_chars += len(str(rec_delta.get("text", "")))
                                                if not tag_done and str(rec_delta.get("text", "")).strip():
                                                    tag_injected = guard_anthropic_stream_delta(rec_delta, tier_tag) or tag_injected
                                                    tag_done = True
                                        except json.JSONDecodeError:
                                            pass
                                    yield (rec_line + "\n").encode("utf-8")
                except httpx.HTTPError:
                    pass
                if not rec_stop:
                    yield _anthropic_terminal_events(
                        "[HARNESS_GATEWAY] auto-recovery continuation unavailable; "
                        "stop-loss: verify missing facts via MCP/L2 tools, or state the minimal unknown and next actions."
                    )
            if not completed and not tripped:
                yield _anthropic_terminal_events(
                    "[HARNESS_GATEWAY_ERROR] All upstream candidates failed for this request; stop-loss synthesized. Upstream: "
                    + _failure_summary(failures, selection.skipped_reasons)
                )

            qm.record_usage(
                chosen_key,
                prompt_tokens=max(1, len(json.dumps(body.get("messages", []))) // 3),
                completion_tokens=max(1, out_chars // 3),
                thinking_tokens=max(0, guard.thinking_chars // 3),
                now_utc=now,
            )
            _log_trace({
                "ts": now.isoformat(),
                "protocol": "anthropic",
                "tier": decision.tier,
                "selected_model": chosen_key,
                "upstream_failures": failures or None,
                "stream": True,
                "thinking_chars": guard.thinking_chars,
                "pivot_count": guard.pivot_count,
                "tripped": tripped or guard.tripped,
                "agent_id": agent_id or None,
                "tag_injected": tag_injected,
                "contract_violations": contract_violations or None,
            })

        return StreamingResponse(
            sse_proxy(),
            media_type="text/event-stream",
            headers={
                "X-Harness-Routed-Tier": decision.tier,
                "X-Harness-Selected-Model": chosen_key,
                "X-Harness-Tier-Tag": tier_tag,
            },
        )

    return app


app = create_app()
