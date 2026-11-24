## Summary

Both Google models (`google-ai-gemini-4-neon`, `google-ai-gemini-4-hydrogen`) returned HTTP 400 on 2026-11-24 when the gateway failed over to them after a tool call:

```
Function call is missing a thought_signature in functionCall parts. This is required for tools to work
```

Trace: `traces/gateway_traces.jsonl`, 2026-11-24T08:09:32Z, `tier: system_2_plus`, `stream: true`.

## Impact

With the primary pool exhausted and Zhipu/Kimi/Copilot unavailable, there was no working upstream left, so the request ended in a stop-loss error and the user's turn was lost ("input stuck").

## Root cause

Google is served through the OpenAI-compatible endpoint. Gemini 3 attaches a thought signature to each tool call (`tool_calls[].extra_content.google.thought_signature`) and expects it on the next request. The gateway had no handling for this field, and the client does not send it back.

## Fix (in progress on `feat/structured-interim-p1`)

`proxy_gateway/thought_signature_store.py`: records signatures from streamed and non-streamed Google tool calls and re-attaches them to assistant `tool_calls` before the request is forwarded. Matching is by tool-call id only; non-Google upstreams and requests that already carry the field are untouched.

## Status / acceptance

- Unit tests: 6 new (`tests/test_thought_signature_store.py`), full suite 362 OK (runner=docker).
- Image rebuilt; module hash in the container matches the repository.
- **Not reproduced end to end.** A two-turn tool-call round trip through the router returned 200 on both Google models with and without `system_2_plus` / `reasoning_effort: high`, and the upstream sent no signature in those requests. So the fix is not yet proven against the real failure.

## Monitoring rule

If `missing a thought_signature` appears again in `gateway_traces.jsonl`, the fix does not cover the failing request shape. Next step then: capture that request body and compare it with the simple repro (number of tools, parallel tool calls, history produced by other providers).
