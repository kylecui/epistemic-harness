## Summary

When every upstream for a request failed or was cooling down, the gateway returned HTTP 200 and emitted a synthesized assistant message:

```
[HARNESS_GATEWAY_ERROR] All upstream candidates failed for this request; stop-loss synthesized. Upstream: ...
```

The client stores that as a normal assistant reply and ends the turn. To the user a quota outage looks like a stuck conversation, and nothing tells them how long to wait.

Observed twice on 2026-11-24 (session transcript entries 2068-2074 and the 08:09Z failure): primary pool exhausted, the rest of the chain unavailable.

## Root cause

The stream routes built the response inside a `StreamingResponse` body generator and yielded the error text as an SSE frame; the non-stream route returned 502. There was no path that reported "nothing was generated" as an HTTP error.

## Fix

`AllUpstreamsUnavailable` is raised when no candidate produced any byte, and answered as HTTP 503 with `Retry-After` (seconds until the soonest-recovering model among those actually attempted):

- body `{"error":{"type":"harness_gateway_error","message":...}}` on the OpenAI route, `{"type":"error","error":{"type":"overloaded_error","message":...}}` on the Anthropic route
- the first stream chunk is pulled inside the endpoint (`_primed`), because `StreamingResponse` sends the status line before iterating the body, so an exception inside the body iterator cannot change the status
- if bytes from some candidate already reached the client, the error stays in-band (the status line is gone)

pi does not retry on its own (pi-ai `maxRetries` defaults to 0), so the user sees an error with the wait time and decides when to retry.

## Verification

- 6 new tests (`tests/test_unavailable_503.py`); full suite 373 OK, runner=docker
- real uvicorn (not only TestClient): OpenAI stream, OpenAI non-stream and Anthropic stream all return 503, `Retry-After: 91` for an upstream `retry-after: 90`, zero SSE frames
- healthy request through the rebuilt router: 200

## Follow-up (optional)

A client-side auto-retry for 503 with a short `Retry-After` would need pi to pass `maxRetries > 0`; not done here.
