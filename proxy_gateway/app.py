#!/usr/bin/env python3
"""Phase 2 Local Dual-Protocol LLM Proxy Gateway (Multi-Provider Quota + Peak + Anti-Thrashing)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import difflib
import hashlib
import json
import uuid
import os
import sys
import tempfile
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
from proxy_gateway.thought_signature_store import thought_signature_store
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
from proxy_gateway.quota_manager import ModelSelection, QuotaManager
from proxy_gateway.interim_guard import interim_mode, requested_interim_schema, check_interim_response, interim_note, enforce_directive
from proxy_gateway.thrashing_guard import GuardState, RECOVERY_DIRECTIVE

REPO_ROOT = Path(__file__).resolve().parent.parent
# One state directory for everything that must not be shared between a running gateway and
# anything else (unit tests, a lab instance). HARNESS_TRACES_DIR already steers response_guard.


def _default_state_dir() -> Path:
    """Under a test runner the live gateway's state is never the default, whatever the import style.

    2026-11-24: `unittest discover -s tests` imports test modules as top-level modules, so
    tests/__init__.py never ran and the suite wrote fake 503 events into the running gateway's trace log.
    The runner is detected from sys.modules instead, and the env var is set so the other writers follow.
    """
    if "unittest" in sys.modules or "pytest" in sys.modules:
        test_dir = tempfile.mkdtemp(prefix="harness-test-traces-")
        os.environ["HARNESS_TRACES_DIR"] = test_dir
        return Path(test_dir)
    return REPO_ROOT / "traces"


STATE_DIR = Path(os.environ.get("HARNESS_TRACES_DIR") or _default_state_dir()).resolve()
TRACE_FILE = STATE_DIR / "gateway_traces.jsonl"
DEFAULT_QUOTA_POLICY = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"
DEFAULT_QUOTA_DB = STATE_DIR / "quota_ledger.db"
FAILED_REQUEST_DIR = STATE_DIR / "failed_requests"
_FAILED_REQUEST_KEEP = 30  # newest files kept; traces/ is gitignored


def capture_failed_request(model_key: str, status: int, payload: Any, upstream_body: str) -> str | None:
    """Keep the exact upstream request on a field-level rejection (HTTP 400).

    A 400 means the request shape itself is wrong; without the payload the failure
    cannot be reproduced (2026-11-24, issue #18). Local diagnostics only: traces/ is
    gitignored and holds the newest 30 captures.
    """
    if status != 400 or not isinstance(payload, dict):
        return None
    try:
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) > 8_000_000:
            return None
        FAILED_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        target = FAILED_REQUEST_DIR / f"{stamp}-{model_key}-400.json"
        # Two captures can land on the same microsecond (seen on the Windows host: 29 of 30
        # kept, because the second overwrote the first). Never overwrite: suffix until free.
        suffix = 0
        while target.exists():
            suffix += 1
            target = FAILED_REQUEST_DIR / f"{stamp}-{model_key}-{suffix}-400.json"
        target.write_text(json.dumps({"model_key": model_key, "status": status,
                                       "upstream_body": (upstream_body or "")[:4000],
                                       "request": payload}, ensure_ascii=False), encoding="utf-8")
        for old in sorted(FAILED_REQUEST_DIR.glob("*.json"))[:-_FAILED_REQUEST_KEEP]:
            old.unlink(missing_ok=True)
        return target.name
    except OSError:
        return None


class AllUpstreamsUnavailable(Exception):
    """Every candidate failed or is cooling down, so nothing was generated for this request.

    Reported to the client as HTTP 503 + Retry-After instead of a synthesized assistant message:
    a fake reply ends the turn silently, an error lets the user retry (2026-11-24).
    """

    def __init__(self, protocol: str, tier: str, summary: str, retry_after: int | None,
                 upstream: dict[str, Any] | None = None) -> None:
        super().__init__(summary)
        self.protocol = protocol
        self.tier = tier
        self.summary = summary
        self.retry_after = retry_after
        self.upstream = upstream  # the first upstream that actually answered: {status, body}


def unavailable_response(exc: AllUpstreamsUnavailable) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after or 30), "X-Harness-Routed-Tier": exc.tier,
               "X-Harness-All-Upstreams-Unavailable": "1"}
    # The status stays the gateway's 503 (deterministic for clients), but the message LEADS with the
    # first upstream that actually answered (its status, code, message, request id), because the
    # client UI shows only error.message. Its raw status and body ride along as structured data.
    upstream = exc.upstream or {}
    lead = str(upstream.get("brief") or "")
    message = (f"{lead}. " if lead else "") + \
              "[HARNESS_GATEWAY_ERROR] No upstream produced a response for this request; nothing was generated."
    if exc.retry_after:
        message += f" Earliest recovery in about {exc.retry_after}s."
    message += f" Candidates: {exc.summary}"
    if exc.protocol == "anthropic":
        content: dict[str, Any] = {"type": "error", "error": {"type": "overloaded_error", "message": message}}
    else:
        content = {"error": {"type": "harness_gateway_error", "message": message}}
    if upstream:
        content["harness"] = {"all_upstreams_unavailable": True, "retry_after_sec": int(headers["Retry-After"]),
                              "upstream_error": {"model": upstream.get("model"), "status": upstream.get("status"),
                                                  "body": str(upstream.get("body") or "")[:2000]},
                              "other_candidates": exc.summary}
    return JSONResponse(status_code=503, content=content, headers=headers)


async def _prepend(first: bytes, rest: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    yield first
    async for chunk in rest:
        yield chunk


async def _primed(stream: AsyncIterator[bytes]) -> bytes | None:
    """Pull the first chunk inside the endpoint so a failure before it can still set the status code.

    StreamingResponse sends the response start line BEFORE it iterates the body (Starlette 1.10,
    responses.py: ``http.response.start`` precedes ``async for chunk in self.body_iterator``), so an
    exception raised inside the body iterator arrives too late to become a 503. Returns None when the
    stream ends without yielding anything.
    """
    try:
        return await stream.__anext__()
    except StopAsyncIteration:
        return None


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
        # Drop any incoming authorization header (case-insensitive) before merging so httpx never sends
        # duplicate Authorization headers (which Copilot rejects as "invalid token: invalid whitespace").
        hdrs = {k: v for k, v in hdrs.items() if k.lower() != "authorization"}
        cop = copilot_auth()
        for k, v in cop.headers(resolve_body).items():
            hdrs[k.lower()] = v
    elif auth_mode == "google":
        key = qm.resolve_api_key(model_key)
        if key:
            for name, value in google_headers(key).items():
                hdrs[name.lower()] = value
    elif auth_mode == "bearer":
        # Providers that accept the plan key as a plain Bearer token (e.g. the
        # zcode agent gateway) instead of anthropic-style x-api-key.
        key = qm.resolve_api_key(model_key)
        if key:
            hdrs["authorization"] = f"Bearer {key}"
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


def _attach_thought_signatures(rewritten: dict[str, Any], target_base: str) -> None:
    """Gemini 3 refuses a follow-up request whose tool_calls lost the thought_signature."""
    if "generativelanguage" in target_base:
        thought_signature_store.inject(rewritten)


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


_REQUEST_ID_HEADERS = ("request-id", "x-request-id", "x-goog-request-id", "x-amzn-requestid", "x-trace-id")


def _error_brief(status: int, body_text: str, headers: Any) -> str:
    """One line per failed upstream: status, the provider's error code, its message, request id.

    The request id is what a provider's support asks for; without it a failure cannot be traced
    on their side (2026-11-24).
    """
    code = message = ""
    try:
        err = json.loads(body_text or "")
        if isinstance(err, dict) and isinstance(err.get("error"), dict):
            err = err["error"]
        if isinstance(err, dict):
            code = str(err.get("status") or err.get("code") or err.get("type") or "")
            message = str(err.get("message") or "")
    except (ValueError, TypeError):
        pass
    if not message:
        message = " ".join((body_text or "").split())
    parts = [f"HTTP {status}"]
    if code:
        parts.append(f"[{code}]")
    parts.append(message[:200])
    try:
        rid = next((str(headers[h]) for h in _REQUEST_ID_HEADERS if headers.get(h)), "")
    except (AttributeError, TypeError):
        rid = ""
    return " ".join(p for p in parts if p) + (f" (request_id={rid})" if rid else "")


async def _record_upstream_failure(
    qm: Any, model_key: str, resp: Any, failures: dict[str, str], now: Any, streaming: bool = False,
    request_payload: Any = None, first_failure: dict[str, Any] | None = None,
) -> None:
    """Classify an upstream HTTP failure (cooldown by status class) and keep a sanitized reason."""
    try:
        if streaming:
            await resp.aread()
        body_text = resp.text or ""
    except Exception:  # noqa: BLE001
        body_text = ""
    qm.mark_upstream_failure(model_key, resp.status_code, body_text, _parse_retry_after(resp), now_utc=now)
    capture_failed_request(model_key, resp.status_code, request_payload, body_text)
    failures[model_key] = _error_brief(resp.status_code, body_text, resp.headers)
    if first_failure is not None and not first_failure:
        first_failure.update(status=resp.status_code, body=body_text[:8000], model=model_key,
                            brief=failures[model_key])


def _failure_summary(failures: dict[str, str], skipped: dict[str, str]) -> str:
    parts = [f"{k} -> {v}" for k, v in failures.items()]
    parts += [f"{k} -> skipped({v})" for k, v in skipped.items() if k not in failures and not v.startswith("held_in_last")]
    return "; ".join(parts)[:2400] or "no candidate attempted"


# --- pinned-model honesty (issue #22) --------------------------------------------------------
# A client that names a model gets one of three answers, and none of them is a silent swap:
#   unknown id          -> HTTP 400 unknown_model, naming near matches and ids we do serve
#   known, not servable -> HTTP 200 with the swap reported (X-Harness-Pin-Dropped plus the body
#                          marker); failover still runs, because the operator decision of
#                          2026-11-24 keeps a pinned model on the normal failover path
#   honoured            -> the pinned model answers, and the served header equals the request
# The swap is announced twice, because pi reads the body and never the headers:
#   X-Harness-Requested-Model / X-Harness-Requested-Model-Served / X-Harness-Pin-Dropped /
#   X-Harness-Skip-Reasons                                                   (headers)
#   harness.pin_dropped.{requested_model, served_model, reason, skipped_reasons}   (body)
PIN_HEADER_REQUESTED = "X-Harness-Requested-Model"
PIN_HEADER_SERVED = "X-Harness-Requested-Model-Served"
PIN_HEADER_SERVED_ONLY = "X-Harness-Served-Model"
PIN_HEADER_DROPPED = "X-Harness-Pin-Dropped"
PIN_HEADER_SKIP_REASONS = "X-Harness-Skip-Reasons"
PIN_HEADER_ALLOW_SUBSTITUTE = "X-Harness-Allow-Substitute"
PIN_SKIP_REASON_LIMIT = 5


def _header_safe(value: str, limit: int = 200) -> str:
    """Header values are latin-1: a client-supplied model id must never break the response."""
    return " ".join(str(value).split())[:limit].encode("latin-1", "replace").decode("latin-1")


def fail_on_unknown_model() -> bool:
    """Default on. Off is for drop-in clients that label turns with their own model ids (Claude Code
    sends `claude-sonnet-4-5-...`, which this catalog will never contain); the label is then routed
    by tier and still reported as a dropped pin in the headers and the trace."""
    return os.getenv("HARNESS_FAIL_ON_UNKNOWN_MODEL", "on").strip().lower() not in ("off", "0", "false")


def resolve_model_alias(qm: QuotaManager, requested: str | None, protocol: str | None = None) -> str | None:
    """Map a client-sent model id to a catalog key; None when the id names nothing we serve.

    Clients send what their own catalog holds: usually our key (`zhipu-glm-5.4`), sometimes the
    provider's id (`glm-5.4`). Both are the same pin, so both resolve to the key the chain uses.
    One upstream id can belong to two catalog keys (openai and anthropic variants), so the route's
    own protocol wins before the first match.
    """
    req = str(requested or "").strip()
    if not req:
        return None
    if req in qm.models:
        return req
    low = req.lower()
    for key in qm.models:
        if key.lower() == low:
            return key
    upstream = [(key, str(cfg.get("upstream_model") or "").strip().lower()) for key, cfg in qm.models.items()]
    for key, up in upstream:
        if up == low and (protocol is None or str(qm.models[key].get("protocol") or "") == protocol):
            return key
    for key, up in upstream:
        if up == low:
            return key
    return None


def near_model_matches(qm: QuotaManager, requested: str, limit: int = 5) -> list[str]:
    """Catalog ids close to the typo, so the 400 tells the client what it probably meant."""
    ids = list(qm.models)
    for cfg in qm.models.values():
        up = str(cfg.get("upstream_model") or "")
        if up and up not in ids:
            ids.append(up)
    return difflib.get_close_matches(str(requested).strip(), ids, n=limit, cutoff=0.4)


def format_skip_reasons(skipped: dict[str, str], limit: int = PIN_SKIP_REASON_LIMIT) -> str:
    """`a=b;c=d`, capped, so a header stays small and the reason list stays readable."""
    return ";".join(f"{k}={v}" for k, v in list(skipped.items())[:limit])


def available_model_ids(qm: QuotaManager, limit: int = PIN_SKIP_REASON_LIMIT) -> list[str]:
    """The ids a 404 may name: stable order, capped, so the message stays one line."""
    return sorted(qm.models)[:limit]


def allow_substitution(request: Request) -> bool:
    """Substitution is opt-in: a pin the client did not release must fail, not quietly move."""
    raw = str(request.headers.get(PIN_HEADER_ALLOW_SUBSTITUTE) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def pin_retry_seconds(qm: QuotaManager, model_key: str | None, tier: str, now: datetime) -> int | None:
    """How long until the pinned model can be served again: cooldowns AND operator holds.

    `soonest_available_in` only knows cooldowns, so a 4h manual hold would otherwise be reported
    as "retry in 1s" and turn an honest refusal into a hot retry loop.
    """
    if not model_key:
        return qm.soonest_available_in(tier, now)
    waits = [qm.soonest_available_in(tier, now, [model_key])]
    pool_id, _ = qm.pool_for_model(model_key)
    holds = qm.active_holds(now)
    for target in (model_key, pool_id):
        entry = holds.get(target)
        if entry:
            waits.append(max(1, int(entry.get("remaining_sec") or 0) + 1))
    live = [w for w in waits if w]
    return max(live) if live else None


@dataclass(frozen=True)
class PinOutcome:
    """What the client pinned vs. what the router will serve (issue #22)."""

    requested: str | None = None
    resolved: str | None = None
    served: str | None = None
    dropped_reason: str | None = None
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def unknown(self) -> bool:
        return bool(self.requested) and self.resolved is None

    @property
    def refused(self) -> bool:
        """The client pinned a model this request will not serve."""
        return bool(self.resolved) and self.served != self.resolved

    def refusal(self, protocol: str, tier: str, qm: QuotaManager, now: datetime) -> AllUpstreamsUnavailable:
        """The 503 a dropped pin produces: the real reason and retry time, not a substitute."""
        retry = pin_retry_seconds(qm, self.resolved, tier, now)
        summary = (f"requested model {self.resolved} is unavailable "
                   f"({self.dropped_reason or 'not_selected'})")
        if retry:
            summary += f" - retry in {retry // 60}m" if retry >= 120 else f" - retry in {retry}s"
        summary += f"; serving a different model requires {PIN_HEADER_ALLOW_SUBSTITUTE}: 1"
        return AllUpstreamsUnavailable(protocol, tier, summary, retry)

    def headers(self) -> dict[str, str]:
        """A named pin always says what it asked for and what it got; an unnamed request stays quiet."""
        if not self.requested:
            return {}
        out = {PIN_HEADER_REQUESTED: _header_safe(self.requested),
               PIN_HEADER_SERVED: _header_safe(self.served or "")}
        if self.refused:
            out[PIN_HEADER_SERVED_ONLY] = _header_safe(self.served or "")
            out[PIN_HEADER_DROPPED] = _header_safe(self.dropped_reason or "not_selected")
            reasons = format_skip_reasons(self.skipped)
            if reasons:
                out[PIN_HEADER_SKIP_REASONS] = _header_safe(reasons, 400)
        return out

    def trace_fields(self) -> dict[str, Any]:
        """requested_model + skipped_reasons ride on every trace, so a swap stays countable."""
        return {"requested_model": self.requested,
                "requested_model_resolved": self.resolved,
                "pin_dropped": self.dropped_reason,
                "skipped_reasons": self.skipped or None}

    def body_marker(self) -> dict[str, Any] | None:
        """`harness` block for the non-stream body: pi reads the body, never the headers."""
        if not self.refused:
            return None
        return {"pin_dropped": {"requested_model": self.requested, "served_model": self.served,
                                "reason": self.dropped_reason or "not_selected",
                                "skipped_reasons": format_skip_reasons(self.skipped)},
                # Same facts flat, so a client can read them without knowing the nested shape.
                "requested_model": self.requested, "served_model": self.served,
                "substituted": True, "reason": self.dropped_reason or "not_selected",
                "skipped_reasons": format_skip_reasons(self.skipped)}


def unknown_model_response(qm: QuotaManager, requested: str, protocol: str) -> JSONResponse:
    """HTTP 404 `unknown_model` for an id that names nothing in the catalog: a ghost pin must not
    look served.

    404, not 400: the request shape is fine and only the named resource is missing, so the client
    stops and fixes the id instead of treating its own payload as malformed. The message lists near
    matches (or the first ids we do serve), and the request never reaches an upstream.
    """
    near = near_model_matches(qm, requested)
    available = near or available_model_ids(qm)
    message = (f"unknown_model: '{requested}' is not in the gateway's model catalog. "
               f"Available model ids: {', '.join(available)}.")
    error = {"type": "unknown_model", "code": "unknown_model", "param": "model",
             "message": message, "near_matches": near,
             "available_models": available_model_ids(qm)}
    if protocol == "anthropic":
        return JSONResponse(status_code=404, content={"type": "error", "error": error})
    return JSONResponse(status_code=404, content={"error": error})


def pin_outcome(qm: QuotaManager, requested: str | None, tier: str, protocol: str,
                selection: ModelSelection, strict_unknown: bool = True) -> PinOutcome:
    """Compare the pin with the selection and name the reason whenever the pin did not win.

    `requested` is the id the CLIENT named: a model the gateway merely preferred (an agent
    profile's pick) is not a pin, so it must never turn into a refusal.
    """
    raw = str(requested or "").strip() or None
    skipped = selection.skipped_reasons
    if not raw:
        return PinOutcome(None, None, selection.model_key, skipped=skipped)
    resolved = resolve_model_alias(qm, raw, protocol)
    if resolved is None:
        reason = None if strict_unknown else "unknown_model(accepted_as_label)"
        return PinOutcome(raw, None, selection.model_key, reason, skipped=skipped)
    if resolved == selection.model_key:
        return PinOutcome(raw, resolved, selection.model_key, skipped=skipped)
    reason = skipped.get(resolved)
    if not reason:
        # Not a skip the router recorded: the pin was never a candidate on this route/tier.
        model = qm.models.get(resolved, {})
        model_protocol = str(model.get("protocol") or protocol)
        if resolved not in (qm.routing_chains.get(tier) or []):
            reason = f"not_in_tier_chain({tier})"
        elif model_protocol != protocol:
            reason = f"protocol_mismatch(model={model_protocol},route={protocol})"
        else:
            reason = "not_selected"
    return PinOutcome(raw, resolved, selection.model_key, reason, skipped=skipped)


def create_app(
    openai_upstream: str | None = None,
    anthropic_upstream: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    quota_manager: QuotaManager | None = None,
    now_provider: Any = None,
) -> FastAPI:
    app = FastAPI(title="Epistemic Harness Proxy Gateway", version="0.3.1")
    # --- lifecycle escape hatch (issue: router is the ONLY LLM exit) ---
    global _IN_FLIGHT, _DRAIN
    _IN_FLIGHT = 0
    _DRAIN = False

    @app.middleware("http")
    async def _inflight_middleware(request: Request, call_next: Any) -> Any:
        global _IN_FLIGHT
        if _DRAIN and request.url.path in ("/v1/chat/completions", "/anthropic/v1/messages"):
            return JSONResponse(
                status_code=503, content={"error": {"type": "draining", "message": "gateway draining for restart"}},
                headers={"Retry-After": "5"},
            )
        _IN_FLIGHT += 1
        try:
            return await call_next(request)
        finally:
            _IN_FLIGHT -= 1

    def _admin_authorized(request: Request) -> bool:
        token = os.getenv("HARNESS_ADMIN_TOKEN")
        return bool(token) and request.headers.get("x-admin-token") == token

    @app.post("/admin/drain")
    async def admin_drain(request: Request) -> Any:
        """Graceful-restart hook: refuse NEW chat requests (503+Retry-After so
        clients retry), let in-flight ones finish. Pair with scripts/router_safe_restart.py."""
        if not _admin_authorized(request):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        global _DRAIN
        _DRAIN = True
        return {"drain": True, "in_flight": _IN_FLIGHT}

    @app.post("/admin/undrain")
    async def admin_undrain(request: Request) -> Any:
        if not _admin_authorized(request):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        global _DRAIN
        _DRAIN = False
        return {"drain": False, "in_flight": _IN_FLIGHT}

    @app.get("/admin/status")
    async def admin_status(request: Request) -> Any:
        if not _admin_authorized(request):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        return {"in_flight": _IN_FLIGHT, "drain": _DRAIN}

    oa_fallback = (openai_upstream or os.getenv("UPSTREAM_OPENAI_URL", "https://api.openai.com/v1")).rstrip("/")
    an_fallback = (anthropic_upstream or os.getenv("UPSTREAM_ANTHROPIC_URL", "https://api.anthropic.com")).rstrip("/")
    qm = quota_manager or QuotaManager(DEFAULT_QUOTA_POLICY, DEFAULT_QUOTA_DB, holds_path=STATE_DIR / "holds.json")
    if quota_manager is None and os.getenv("HARNESS_REMOTE_USAGE", "on") != "off" \
            and not ("unittest" in sys.modules or "pytest" in sys.modules):
        # Provider-reported usage for pools that declare usage_endpoint (OpenCode). Only for the
        # gateway's own manager: tests inject theirs and never touch the network.
        qm.start_remote_usage_refresh()
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
        snap = qm.status_snapshot(get_now())
        snap["holds"] = qm.active_holds(get_now())
        snap["alerts"] = qm.over_cap_alerts(get_now())
        return snap

    def _quota_alert_header() -> dict[str, str]:
        """Advertising a plan overrun on every response is what lets the client warn the operator."""
        alerts = qm.over_cap_alerts(get_now())
        return {"X-Harness-Quota-Alert": "; ".join(alerts)[:200]} if alerts else {}

    @app.post("/admin/hold")
    async def admin_hold(request: Request) -> Any:
        """Operator control: block a model key or a pool id for N minutes."""
        if not _admin_authorized(request):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        body = await request.json()
        target = str(body.get("target") or "").strip()
        if not target:
            return JSONResponse(status_code=400, content={"error": "target required (model key or pool id)"})
        if target not in qm.models and target not in qm.pools:
            # A typo must never look like success: the operator would believe the model is blocked.
            return JSONResponse(status_code=404, content={
                "error": f"unknown target: {target}",
                "models": sorted(qm.models), "pools": sorted(qm.pools)})
        return qm.hold(target, int(body.get("minutes") or 60), str(body.get("reason") or ""))

    @app.post("/admin/unhold")
    async def admin_unhold(request: Request) -> Any:
        if not _admin_authorized(request):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        body = await request.json()
        return qm.release(str(body.get("target") or "").strip())

    @app.get("/traces")
    async def list_traces(limit: int = 20) -> dict[str, Any]:
        if not TRACE_FILE.exists():
            return {"traces": []}
        lines = TRACE_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
        return {"traces": [json.loads(line) for line in lines if line.strip()]}

    @app.exception_handler(AllUpstreamsUnavailable)
    async def _all_upstreams_unavailable(request: Request, exc: AllUpstreamsUnavailable) -> JSONResponse:
        # Every 503 leaves one trace event, whichever route raised it, so its frequency and
        # wait time can be counted (monitoring rule: auto-retry only pays off for short waits).
        _log_trace({"ts": get_now().isoformat(), "event": "all_unavailable", "protocol": exc.protocol,
                    "tier": exc.tier, "retry_after": exc.retry_after, "detail": exc.summary,
                    "upstream_status": (exc.upstream or {}).get("status")})
        return unavailable_response(exc)

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
        # A machine consumer (judge, experiment arm, probe) asks for the model's own text. The
        # header must suppress the tag INJECTION too, not just the checks: a reply starting with
        # "[Tier: ...]" is unusable JSON for the caller (2026-11-25: judges answered in prose).
        tier_tag = (build_tier_tag(decision.tier, detect_mode(user_text, decision.tier))
                    if _contract_check_enabled(request) else "")
        tag_injected = False
        requested_model = body.get("model")
        if not requested_model and profile and profile.get("model"):
            requested_model = str(profile["model"]).strip()
        # An id that names nothing in the catalog is a client error, not a hint to pick something
        # else (issue #22: a pin to a ghost id was silently served by whichever model came first).
        requested_key = resolve_model_alias(qm, requested_model, "openai")
        strict_unknown = fail_on_unknown_model()
        if requested_model and requested_key is None and strict_unknown:
            _log_trace({"ts": now.isoformat(), "event": "unknown_model", "protocol": "openai",
                        "tier": decision.tier, "requested_model": str(requested_model)[:200],
                        "agent_id": agent_id or None,
                        "near_matches": near_model_matches(qm, requested_model)})
            return unknown_model_response(qm, str(requested_model), "openai")
        sess_id = request.headers.get("x-harness-session-id", "default")
        exclude_pool = resolve_excluded_pool(
            dict(request.headers), qm, session_last_pool, sess_id,
            decision.cross_family_critic, drafter_state["last_pool"],
        )
        selection = qm.select_candidates(
            decision.tier,
            "openai",
            requested_key,
            now_utc=now,
            fallback_base_url=oa_fallback,
            exclude_pool=exclude_pool,
            # The chair names the main agent in the request body and sends no agent header; that pick
            # is not moved for price. Sub-agent traffic (X-Harness-Agent-Id) follows the peak rules.
            pin_requested=bool(body.get("model")) and not agent_id,
        )
        # A body model is a pin only for the chair's own request; sub-agent traffic keeps the peak
        # rules (operator decision 2026-11-24), so its label must not turn into a refusal.
        client_pin = (str(body.get("model") or "").strip() or None) if not agent_id else None
        pin = pin_outcome(qm, client_pin, decision.tier, "openai", selection, strict_unknown)
        if pin.refused and not allow_substitution(request):
            # A pin we cannot honour is reported, never swapped out (issue #22): 503 + Retry-After,
            # with the reason in error.message, so the client retries the model it asked for.
            _log_trace({"ts": now.isoformat(), "event": "pin_refused", "protocol": "openai",
                        "tier": decision.tier, "requested_model": pin.requested,
                        "pin_dropped": pin.dropped_reason,
                        "skipped_reasons": selection.skipped_reasons,
                        "agent_id": agent_id or None})
            raise pin.refusal("openai", decision.tier, qm, now)
        session_last_pool[sess_id] = selection.pool_id
        if not decision.cross_family_critic:
            drafter_state["last_pool"] = selection.pool_id
        is_stream = bool(body.get("stream", False))
        guard = GuardState(decision.tier, decision.max_thinking_chars, decision.max_pivots)
        chosen_key = selection.model_key

        if not is_stream:
            last_resp: httpx.Response | None = None
            failures: dict[str, str] = {}
            first_failure: dict[str, Any] = {}  # first upstream that actually answered
            async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as client:
                for mkey in selection.failover_chain:
                    chosen_key = mkey
                    rewritten = inject_thinking_language_openai(rewrite_openai_payload(body, decision), thinking_lang_mode)
                    rewritten["model"] = qm.models[mkey]["upstream_model"]
                    target_base = _resolve_base(qm, mkey, oa_fallback)
                    rewritten = sanitize_openai_payload(rewritten, target_base)
                    _attach_thought_signatures(rewritten, target_base)
                    resp = await client.post(
                        f"{target_base}/chat/completions",
                        json=rewritten,
                        headers=_build_upstream_headers(request, qm, mkey, "openai", rewritten),
                    )
                    last_resp = resp
                    if _is_failover_status(resp.status_code):
                        await _record_upstream_failure(qm, mkey, resp, failures, now, request_payload=rewritten, first_failure=first_failure)
                        continue
                    break

            assert last_resp is not None
            if failures and _is_failover_status(last_resp.status_code):
                raise AllUpstreamsUnavailable(
                    "openai", decision.tier, _failure_summary(failures, selection.skipped_reasons),
                    qm.soonest_available_in(decision.tier, now, failures), first_failure or None)
            data = last_resp.json()
            if last_resp.status_code >= 400:
                # Issue #12: a provider may answer with a list (or a bare string) instead of an
                # OpenAI-shaped envelope. Passing it through verbatim breaks every client parser
                # that expects {"error": ...}, so non-conforming bodies are wrapped, not forwarded.
                if not (isinstance(data, dict) and data.get("error")):
                    data = {"error": {"type": "upstream_error", "status": last_resp.status_code,
                                      "message": _error_brief(last_resp.status_code,
                                                              json.dumps(data, ensure_ascii=False)[:500],
                                                              last_resp.headers)}}
            elif not isinstance(data, dict):
                data = {"choices": []}
            if "generativelanguage" in target_base:
                thought_signature_store.record_chunk(data)
            # raw upstream text BEFORE gateway tag injection: the interim schema
            # polices the model's output, not the harness's own prefix
            _raw_msg = (data.get("choices") or [{}])[0].get("message") or {}
            _raw_text = _raw_msg.get("content") if isinstance(_raw_msg.get("content"), str) else ""
            if tier_tag:
                tag_injected = guard_openai_message(data, tier_tag)

            # Review-turn output-contract check (issue #1): bounce exactly once
            # with a corrective directive; on repeat violation append an L2
            # escalation intercept instead of looping.
            resp_mode = detect_mode(user_text, decision.tier)
            contract_violations: list[str] = []
            _msg = (data.get("choices") or [{}])[0].get("message") or {}
            _resp_text = _msg.get("content") if isinstance(_msg.get("content"), str) else ""
            _interim_note = _interim_check(request, _raw_text)
            _cap_note: str | None = None
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
                            if tier_tag:
                                tag_injected = guard_openai_message(data, tier_tag)
                except httpx.HTTPError:
                    pass
            if _interim_note and isinstance(_msg.get("content"), str):
                _msg["content"] = f"{_msg['content']}\n\n{_interim_note}"
            if isinstance(_msg.get("content"), str):
                # Cap is computed, not self-declared: align the header before judging.
                # Normalize the FINAL content (tag + any interim note already in it) so
                # writing it back never drops those; the NOTE itself is trace-only
                # (2026-11-24) — appended to content it polluted the transcript and got
                # echoed by the model for turns.
                _msg["content"], _cap_note = normalize_declared_cap(_msg["content"])
                _resp_text = _msg["content"]
            if _resp_text:
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
                            if tier_tag:
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
            _pin_marker = pin.body_marker()
            if _pin_marker and isinstance(data, dict):
                # Same two facts as the headers, for clients that cannot read them.
                data["harness"] = {**(data.get("harness") if isinstance(data.get("harness"), dict) else {}),
                                   **_pin_marker}
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
                "cap_note": _cap_note,
                "interim_violations": _interim_note or None,
                **pin.trace_fields(),
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
                    **pin.headers(),
                    **_quota_alert_header(),
                },
            )

        async def sse_proxy() -> AsyncIterator[bytes]:
            nonlocal chosen_key
            out_chars = 0
            tag_done = False
            tag_injected = False
            tripped = False
            completed = False
            streamed_any = False  # once a candidate has yielded, the status line is gone
            last_chunk_id = "harness-fallback"
            cap_note_stream: str | None = None
            openai_tag_guard = StreamTagGuard(tier_tag) if tier_tag else None
            failures: dict[str, str] = {}
            first_failure: dict[str, Any] = {}  # first upstream that actually answered
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
                _attach_thought_signatures(rewritten, target_base)
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
                                await _record_upstream_failure(qm, mkey, resp, failures, now, streaming=True,
                                                              request_payload=rewritten, first_failure=first_failure)
                                continue
                            streamed_any = True
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
                                        if "generativelanguage" in target_base:
                                            thought_signature_store.record_chunk(chunk_obj)
                                        if chunk_obj.get("id"):
                                            last_chunk_id = chunk_obj["id"]
                                        choice = (chunk_obj.get("choices") or [{}])[0]
                                        delta = choice.get("delta") or {}
                                        if choice.get("finish_reason"):
                                            saw_finish = True
                                        if delta.get("content"):
                                            full_text += str(delta["content"])
                                            if openai_tag_guard is not None:
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
                        # Cap note goes to the trace + response headers, NEVER into the
                        # transcript (2026-11-24): injected into content it polluted the
                        # conversation and taught the model to echo it on later turns.
                        cap_note_stream = cap_notes[0] if cap_notes else None
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
            all_unavailable = not completed and not tripped

            if not all_unavailable:
                # Nothing was generated, so nothing is charged to the local quota ledger.
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
                "cap_note": cap_note_stream,
                **pin.trace_fields(),
            })
            if all_unavailable:
                if streamed_any:
                    # Bytes already reached the client, so the status line is gone: report in-band.
                    yield _openai_terminal_chunk(
                        "harness-gateway-error",
                        "[HARNESS_GATEWAY_ERROR] an upstream stream failed and no candidate recovered. Upstream: "
                        + _failure_summary(failures, selection.skipped_reasons),
                    ).encode("utf-8")
                else:
                    raise AllUpstreamsUnavailable(
                        "openai", decision.tier, _failure_summary(failures, selection.skipped_reasons),
                        qm.soonest_available_in(decision.tier, now, failures), first_failure or None)

        stream = sse_proxy()
        first_chunk = await _primed(stream)
        if first_chunk is None:
            raise AllUpstreamsUnavailable(
                "openai", decision.tier, "gateway stream produced no output",
                qm.soonest_available_in(decision.tier, now, []))
        return StreamingResponse(
            _prepend(first_chunk, stream),
            media_type="text/event-stream",
            headers={
                "X-Harness-Routed-Tier": decision.tier,
                "X-Harness-Effort": decision.openai_effort,
                "X-Harness-Selected-Model": chosen_key,
                "X-Harness-Peak-Avoided": str(selection.peak_avoided).lower(),
                "X-Harness-Last-Option-Used": str(selection.last_option_used).lower(),
                "X-Harness-Tier-Tag": tier_tag,
                **pin.headers(),
                **_quota_alert_header(),
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
        # A machine consumer (judge, experiment arm, probe) asks for the model's own text. The
        # header must suppress the tag INJECTION too, not just the checks: a reply starting with
        # "[Tier: ...]" is unusable JSON for the caller (2026-11-25: judges answered in prose).
        tier_tag = (build_tier_tag(decision.tier, detect_mode(user_text, decision.tier))
                    if _contract_check_enabled(request) else "")
        tag_injected = False
        requested_model = body.get("model")
        if not requested_model and profile and profile.get("model"):
            requested_model = str(profile["model"]).strip()
        # Same three outcomes as the OpenAI route: a pin to an id we do not serve is a 400, and a pin
        # we cannot honour is reported instead of quietly replaced (issue #22).
        requested_key = resolve_model_alias(qm, requested_model, "anthropic")
        strict_unknown = fail_on_unknown_model()
        if requested_model and requested_key is None and strict_unknown:
            _log_trace({"ts": now.isoformat(), "event": "unknown_model", "protocol": "anthropic",
                        "tier": decision.tier, "requested_model": str(requested_model)[:200],
                        "agent_id": agent_id or None,
                        "near_matches": near_model_matches(qm, requested_model)})
            return unknown_model_response(qm, str(requested_model), "anthropic")
        sess_id = request.headers.get("x-harness-session-id", "default")
        exclude_pool = resolve_excluded_pool(
            dict(request.headers), qm, session_last_pool, sess_id,
            decision.cross_family_critic, drafter_state["last_pool"],
        )
        selection = qm.select_candidates(
            decision.tier, "anthropic", requested_key, now_utc=now,
            fallback_base_url=an_fallback, exclude_pool=exclude_pool,
            pin_requested=bool(body.get("model")) and not agent_id,
        )
        # Same contract as the OpenAI route (issue #22): report, never swap. Sub-agent labels are
        # not pins, so they keep the peak rules instead of being refused.
        client_pin = (str(body.get("model") or "").strip() or None) if not agent_id else None
        pin = pin_outcome(qm, client_pin, decision.tier, "anthropic", selection, strict_unknown)
        if pin.refused and not allow_substitution(request):
            # Same contract as the OpenAI route (issue #22): report, never swap.
            _log_trace({"ts": now.isoformat(), "event": "pin_refused", "protocol": "anthropic",
                        "tier": decision.tier, "requested_model": pin.requested,
                        "pin_dropped": pin.dropped_reason,
                        "skipped_reasons": selection.skipped_reasons,
                        "agent_id": agent_id or None})
            raise pin.refusal("anthropic", decision.tier, qm, now)
        session_last_pool[sess_id] = selection.pool_id
        if not decision.cross_family_critic:
            drafter_state["last_pool"] = selection.pool_id
        is_stream = bool(body.get("stream", False))
        guard = GuardState(decision.tier, decision.max_thinking_chars, decision.max_pivots)

        chosen_key = selection.model_key
        # Per-model upstream base (issue: anthropic path hardcoded the global
        # fallback, so non-Anthropic anthropic-protocol models — zcode gateway,
        # zhipu /api/anthropic — were sent to api.anthropic.com and 401'd).
        an_base = _resolve_base(qm, chosen_key, an_fallback)
        rewritten = inject_thinking_language_anthropic(rewrite_anthropic_payload(body, decision), thinking_lang_mode)
        rewritten["model"] = selection.upstream_model

        if not is_stream:
            # Same failover loop as the OpenAI route. Until 2026-11-24 this path made exactly one
            # attempt and relayed the upstream error, so a second Anthropic-protocol candidate existed
            # in the chain but was never tried.
            last_resp: httpx.Response | None = None
            failures: dict[str, str] = {}
            first_failure: dict[str, Any] = {}  # first upstream that actually answered
            async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as client:
                for mkey in selection.failover_chain:
                    chosen_key = mkey
                    an_base = _resolve_base(qm, mkey, an_fallback)
                    rewritten = inject_thinking_language_anthropic(rewrite_anthropic_payload(body, decision), thinking_lang_mode)
                    rewritten["model"] = qm.models[mkey]["upstream_model"]
                    resp = await client.post(
                        f"{an_base}/v1/messages",
                        json=rewritten,
                        headers=_build_upstream_headers(request, qm, mkey, "anthropic", rewritten),
                    )
                    last_resp = resp
                    if _is_failover_status(resp.status_code):
                        await _record_upstream_failure(qm, mkey, resp, failures, now, request_payload=rewritten,
                                                      first_failure=first_failure)
                        continue
                    break
            assert last_resp is not None
            if failures and _is_failover_status(last_resp.status_code):
                raise AllUpstreamsUnavailable(
                    "anthropic", decision.tier, _failure_summary(failures, selection.skipped_reasons),
                    qm.soonest_available_in(decision.tier, now, failures), first_failure or None)
            data = resp.json()
            guard_anthropic_content(data, tier_tag)

            # Review-turn output-contract check (issue #1): bounce exactly once.
            resp_mode = detect_mode(user_text, decision.tier)
            contract_violations: list[str] = []
            _cap_note: str | None = None
            _blocks = data.get("content") if isinstance(data.get("content"), list) else []
            _resp_text = "".join(
                str(b.get("text")) for b in _blocks
                if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
            )
            if _resp_text:
                # Cap is computed, not self-declared: align the header before judging.
                # NOTE goes to header/trace only (2026-11-24), never into the transcript.
                # Anthropic layout: text lives in content blocks; write the normalized
                # header back into the FIRST text block (header is always up front).
                _resp_text, _cap_note = normalize_declared_cap(_resp_text)
                _first_text = next((b for b in _blocks if isinstance(b, dict) and b.get("type") == "text"), None)
                if _first_text is not None and isinstance(_first_text.get("text"), str):
                    # normalize only swaps L<digit> -> L<digit> (same length), so the
                    # first block keeps its length and takes the normalized prefix.
                    _first_text["text"] = _resp_text[:len(_first_text["text"])]
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
                            f"{an_base}/v1/messages",
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
            _pin_marker = pin.body_marker()
            if _pin_marker and isinstance(data, dict):
                data["harness"] = {**(data.get("harness") if isinstance(data.get("harness"), dict) else {}),
                                   **_pin_marker}
            _log_trace({
                "ts": now.isoformat(),
                "protocol": "anthropic",
                "tier": decision.tier,
                "selected_model": chosen_key,
                "stream": False,
                "tripped": False,
                "agent_id": agent_id or None,
                "contract_violations": contract_violations or None,
                "cap_note": _cap_note,
                **pin.trace_fields(),
            })
            return JSONResponse(
                status_code=resp.status_code,
                content=data,
                headers={
                    "X-Harness-Routed-Tier": decision.tier,
                    "X-Harness-Selected-Model": chosen_key,
                    "X-Harness-Tier-Tag": tier_tag,
                    **pin.headers(),
                    **_quota_alert_header(),
                },
            )

        async def sse_proxy() -> AsyncIterator[bytes]:
            nonlocal chosen_key
            out_chars = 0
            tag_done = False
            tag_injected = False
            tripped = False
            completed = False
            streamed_any = False  # once a candidate has yielded, the status line is gone
            cap_note_stream: str | None = None
            anthropic_tag_guard = StreamTagGuard(tier_tag) if tier_tag else None
            failures: dict[str, str] = {}
            first_failure: dict[str, Any] = {}  # first upstream that actually answered
            resp_mode = detect_mode(user_text, decision.tier)
            full_text = ""
            stop_lines: list[str] = []
            contract_violations: list[str] = []
            for mkey in selection.failover_chain:
                chosen_key = mkey
                an_base = _resolve_base(qm, mkey, an_fallback)
                rewritten = inject_thinking_language_anthropic(rewrite_anthropic_payload(body, decision), thinking_lang_mode)
                rewritten["model"] = qm.models[mkey]["upstream_model"]
                saw_stop = False
                try:
                    async with httpx.AsyncClient(transport=transport, timeout=upstream_timeout) as client:
                        async with client.stream(
                            "POST",
                            f"{an_base}/v1/messages",
                            json=rewritten,
                            headers=_build_upstream_headers(request, qm, mkey, "anthropic", rewritten),
                        ) as resp:
                            if resp.status_code >= 400:
                                await _record_upstream_failure(qm, mkey, resp, failures, now, streaming=True,
                                                              request_payload=rewritten, first_failure=first_failure)
                                continue
                            streamed_any = True
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
                                                if anthropic_tag_guard is not None:
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
                    # Cap note: trace/header only, never into the transcript (2026-11-24).
                    cap_note_stream = cap_notes[0] if cap_notes else None
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
                            f"{an_base}/v1/messages",
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
            all_unavailable = not completed and not tripped

            if not all_unavailable:
                # Nothing was generated, so nothing is charged to the local quota ledger.
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
                "cap_note": cap_note_stream,
                **pin.trace_fields(),
            })
            if all_unavailable:
                if streamed_any:
                    # Bytes already reached the client, so the status line is gone: report in-band.
                    yield _anthropic_terminal_events(
                        "[HARNESS_GATEWAY_ERROR] an upstream stream failed and no candidate recovered. Upstream: "
                        + _failure_summary(failures, selection.skipped_reasons))
                else:
                    raise AllUpstreamsUnavailable(
                        "anthropic", decision.tier, _failure_summary(failures, selection.skipped_reasons),
                        qm.soonest_available_in(decision.tier, now, failures), first_failure or None)

        stream = sse_proxy()
        first_chunk = await _primed(stream)
        if first_chunk is None:
            raise AllUpstreamsUnavailable(
                "anthropic", decision.tier, "gateway stream produced no output",
                qm.soonest_available_in(decision.tier, now, []))
        return StreamingResponse(
            _prepend(first_chunk, stream),
            media_type="text/event-stream",
            headers={
                "X-Harness-Routed-Tier": decision.tier,
                "X-Harness-Selected-Model": chosen_key,
                "X-Harness-Tier-Tag": tier_tag,
                **pin.headers(),
                **_quota_alert_header(),
            },
        )

    return app


app = create_app()
