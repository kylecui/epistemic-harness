# Execution Runner Policy — Docker-first, host as explicit fallback

> Verdict: run verification and execution in containers by default (POSIX shell, pinned Python, fixed line endings). Host-shell execution is the declared fallback for machines without Docker — and the fallback must be recorded, never silent.
> Basis: local measurements + external research (each cited, read 2026-11-21).
> 中文辅助版见 git 历史（v0.4.2 前）；规范以本文为准。

## 1. Why this is not a preference

### [L2] Measured on this machine (same 197-test suite)

| Runner | Wall | In-container | Notes |
|---|---|---|---|
| host venv python | 7.4 s (idle) / 13.9 s (loaded) | — | shell decided by `COMSPEC`, uncontrolled |
| `docker run --rm --network none -v .:/work` | 9.0 s | 3.5–4.6 s | ~2 s container startup; faster inside (no AV scanning, POSIX fs semantics) |
| image build (`python:3.12-slim` + git + requirements) | 27.8 s once | — | reused afterwards |

### [L2] Failures we already hit (all host divergence, not code bugs)

1. **Different shells**: `subprocess.run(shell=True)` uses whatever `COMSPEC` points at. A fixture written with `printf 'a\nb\n'` passed in one environment and went red in another.
2. **Different line endings**: every file in this repo used to be CRLF. A `#!/usr/bin/env bash` script then dies inside a Linux container with `bad interpreter: /bin/bash^M`.
3. **Different interpreters**: `python` on PATH was the 3.12.3 system interpreter without fastapi/pydantic; the venv was the right one.

Containers remove all three at once — but they do **not** fix line endings by themselves. That requires `.gitattributes` (`eol=lf` for sh/py/yaml/ts/md; CRLF kept only for `*.ps1/*.bat/*.cmd`), which this repo now carries.

### [L2] External research

- The execution substrate is itself a variable: single containers / hosted sandboxes / k8s / cloud VMs differ by up to **110× in cold-start latency** and **1.8× in projected worker-hours** over 1M trajectories — tune the substrate as part of the system, not as plumbing. arXiv:2607.01415 — https://arxiv.org/abs/2607.01415
- OS-level execution (tool calls, container/agent init) accounts for **55–60% of end-to-end latency** in containerized coding agents; memory, not CPU, is the bottleneck (peak/avg up to 15.4×). So "one fresh container per check" is wrong — reuse images and batch. arXiv:2602.09345 — https://arxiv.org/abs/2602.09345
- **Verifiers can be bypassed**: 331 terminal-agent environments were shown reward-hackable (output spoofing, stack introspection, stdlib patching, binary hijacking), task-specifically. Verification must run in a controlled environment, and "was the verifier itself modified" must leave evidence. arXiv:2604.17596 — https://arxiv.org/abs/2604.17596

## 2. Policy (implemented)

`.pi/exit_gate.json` carries two fields:

```json
{ "gate_runner": "auto", "verify_image": "epistemic-verify:local" }
```

- `docker` — mandatory container. Missing CLI or missing image → the check fails with `RUNNER_UNAVAILABLE`; **never a silent downgrade**.
- `host` — the default. Existing repos change behavior by zero; shell semantics are whatever the host provides.
- `auto` — container only when the Docker CLI works **and** the image exists locally; otherwise host with the reason printed and written to the ledger.

`CheckSpec` may carry `runner` to override a single check (e.g. one that needs the host node toolchain).

Every evidence record carries a `runner` field; the ledger stores evidence names; `scripts/verify.py` prints `runner=docker image=<img> rev=<sha>` — so "who produced this green" is auditable after the fact.

## 3. Usage

```bash
docker build -f Dockerfile.verify -t epistemic-verify:local .   # once
./scripts/hvx                                        # auto: container when usable
./scripts/hvx --runner docker                        # mandatory; exit 3 without Docker
./scripts/hvx --runner host                          # fallback
docker compose run --rm verify                       # pure-container: no host python at all
```

Containers run with `--network none`: the suite needs no network, and "a check secretly fetching the network" becomes impossible.

## 4. Explicitly NOT containerized (written down, not vague)

- **`dispatch_tooled`**: it must spawn the `pi` binary, which does not exist inside containers; host only.
- **OAuth / device-code logins** (Copilot, Google): need a browser and host credentials.
- **The user's own editor / git hooks**: outside this repo's remit.

## 5. Known risks and mitigations

| Risk | Current state | Mitigation |
|---|---|---|
| verifier script edited by the agent, then self-certified | mount is writable | every green records `rev=<sha>` + `image=<img>`; changes to `scripts/` and `.pi/exit_gate.json` should go through review |
| per-check container restart cost | one `docker run` per check today | batch mode runs a whole check set in one container (sentinel-delimited); switch when check count grows |
| bind-mount slowness on Windows | acceptable (+1.8 s measured) | named-volume caching if it ever matters — semantics unchanged |
| line endings regressing | `.gitattributes` pins LF | enforced again by `scripts/check_eol.py` in the gate and the pre-commit hook |

## 6. Acceptance

```bash
python scripts/verify.py --runner docker                    # exit 0, prints runner=docker
python scripts/verify.py --runner host                      # exit 0, prints runner=host
HARNESS_VERIFY_IMAGE=missing:1 python scripts/verify.py --runner docker   # exit 3 + RUNNER_UNAVAILABLE
python -m unittest tests.test_runner_selection -v           # 8 tests: default host, missing CLI/image, auto fallback, per-check override
```

Must-fail case: `gate_runner=docker` with no image still returning green — that would mean a silent downgrade, a regression.
