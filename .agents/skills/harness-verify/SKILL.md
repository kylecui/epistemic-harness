---
name: harness-verify
description: "Verify the harness is green: unit tests docker-first, line-ending policy, docs/code sync, routing validation. Use when the user says verify, 验证, 跑测试, test suite, hvx."
---

# Run the harness verification suite (tests, eol, docs, routing)

Run from the repo root:
`./scripts/hvx`                    # full suite (Windows: scripts\hvx.ps1)
`./scripts/hvx -p "test_gate*"`    # subset by unittest pattern
Never call bare `python scripts/verify.py` — the wrapper resolves the project interpreter.
