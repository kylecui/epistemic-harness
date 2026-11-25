# Issue remediation plan — 2026-11-25

Written after a session that touched the gateway, the guard, the verify plane and the
experiment campaign. Ordered **newest issue first**, as requested. Each entry is judged
against evidence produced today, not against what the issue said when filed: several
describe behaviour that has since changed, and two are environment conditions rather
than code defects.

## How to read this

| Field | Meaning |
|---|---|
| Status | `open` (reproduced today), `stale` (text predates a fix, re-verify then close), `env` (engine/environment), `wontfix` (decision recorded) |
| Batch | Wave of work, ordered by blocking risk rather than by age |
| Effort | S ≤ 1h, M ≤ half a day, L ≥ a day |
| Acceptance | A check that fails today and passes after the fix; no issue closes without one |

## Triage

| # | Title (short) | Status | Batch | Effort |
|---|---|---|---|---|
| 25 | gated_commit sweeps staged paths (`git add -A`) | open | B1 | S |
| 24 | Container cannot list `/app/skills/pi-native` (ENOMEM) | env | B2 | M |
| 23 | Catalogs advertise unroutable copilot/google models | open | B1 | S |
| 22 | Gateway silently serves another model (pin ignored, no signal) | open | B1 | M |
| 21 | dispatch_subagent pins the whole run in one MCP request | open | B3 | L |
| 19 | Large-write guard bypassable via `codemode` | open | B2 | S |
| 18 | Gemini tool calls 400 (missing thought_signature) | stale | B5 | M |
| 17 | Vendor-agent quota harvesting / zcode fingerprint | wontfix | B5 | – |
| 16 | Write guard suggests tools absent from the session | open | B2 | S |
| 14 | bash heredoc halves backslashes on Windows host | env/upstream | B5 | S |

| 13 | Experiment workloads have no container plane | open | B4 | M |
| 12 | Failover dies on HTTP 400, crashes on list error payloads | stale | B4 | M |
| 11 | README test badge must be hand-synced | open | B1 | S |
| 10 | Cap normalization drags L2 conclusions to L4 | stale | B4 | S |
| 9 | `run_gate` runs caller commands inside the backend container | open | B4 | M |
| 8 | Exit-gate bounce truncates the failing test's identity | open | B2 | S |
| 7 | `dispatch_readonly`/`dispatch_tooled` cannot reach host worktrees | open | B3 | L |
| 6 | Contract intercept demands three-part structure for Tier 0/1 | stale | B4 | S |
| 5 | `harness_version.py` says "aligned" for a stale contract | open | B4 | S |
| 4 | Converge mode lacked a minimum-sufficient-cause gate | stale | B5 | S |

Batch order: **B1** truth of the system (what the router and the history actually do),
**B2** guard and failure reporting, **B3** dispatch architecture, **B4** verification
plane, **B5** closures and monitoring.

## B1 — Truth of the system (do first: everything else is judged through these)

### #25 `gated_commit` sweeps staged paths · S

- **Reproduced today**: staged two files, ran `gated_commit`, and commit `1274f13` carried
  `Dockerfile`, `docker-compose.yml`, both READMEs, the experiment scripts and 30 data files.
  Internal `git add -A` ignores the caller's index.
- **Root cause**: `scripts/gated_commit.py` unconditionally stages everything before committing.
- **Plan**: if `git diff --cached --name-only` is non-empty, commit only the index; otherwise keep
  `git add -A`. Print which mode ran (`staged=3 paths` / `mode=sweep`) so the log says it.
- **Tamper check**: a pre-commit hook that re-adds files would defeat this; the hook we install only
  checks EOL, so no conflict.
- **Acceptance**: staged-only run leaves unrelated edits in the working tree and `git show --stat`
  lists exactly the staged paths; unstaged run behaves as today; both covered by a test that builds
  a throwaway repo.

### #11 README badge hand-sync · S

- **Evidence today**: `docs_fresh` red with `badge not synced: … (count 394)` after the count moved.
- **Root cause**: `scripts/check_docs.py` compares a hand-written number with discovery and nothing
  writes the number.
- **Plan**: `check_docs.py --fix` rewrites the badge; the exit gate runs the fix before comparing,
  so a test addition can never red `docs_fresh` (the check still fails if the badge is *wrong* after
  the fix, which is the real invariant).
- **Acceptance**: add a test file, run the gate without touching docs → green, badge updated;
  hand-corrupt the badge then run `check_docs.py --fix` → corrected.

### #23 Catalogs advertise unroutable models · S

- **Reproduced today**: `~/.pi/agent/models.json` lists 16 router models including
  `copilot-claude-sonnet-5.5`, `copilot-claude-fable-5.2`, `google-ai-gemini-4-neon`,
  `google-ai-gemini-4-hydrogen` — none of which appear in any failover chain.
- **Root cause**: the router block is generated from `quota_policy.yaml` *models*, while routability
  is defined by *chains*; the two sets drifted when Copilot/Google were pulled out of the chains.
- **Plan**: generate the client catalog from the union of chain members (plus deliberately pinned
  pool entries), not from every model block. Keep the definitions in `quota_policy.yaml` so a
  re-entry is a chain edit, and mark any deliberate exception `routable: false` so it is visible
  rather than silently filtered.
- **Acceptance**: a test asserts every model advertised by `install_global.py` appears in at least
  one chain or carries `routable: false`; the generated `models.json` has no copilot/google ids.

### #22 Gateway silently serves a different model · M

- **Reproduced today**: pinning `lab-nonexistent-pin` returned HTTP 200 served by
  `zhipu-glm-5.4`, with no warning header and nothing in the trace (`requested_model=None`).
  The running image predates the trace-field patch, which is itself part of the defect: the
  trace can only answer "what was requested" after a rebuild nobody linked to the fix.
- **Root cause**: `select_candidates(pin_requested=…)` correctly fronts the pinned model, but when
  the pin is unusable the chain falls through silently; the response and the trace carry no
  "you asked for X, you got Y" signal, and an unknown model id is not a client error.
- **Plan**: three distinct outcomes, each observable.
  1. Unknown id (not in the catalog at all) → HTTP 400 `unknown_model`, listing near matches.
  2. Known but unusable (cooled, pool locked, manual hold) → HTTP 200 with
     `X-Harness-Requested-Model-Served: <actual>` plus a `harness.pin_dropped` field naming the
     skip reason, and the same two facts in the trace.
  3. Honoured → `X-Harness-Requested-Model-Served` equals the request and nothing else changes.
- **Prerequisite**: rebuild the gateway image (`docker compose up -d --build`) — the running
  container is older than `app.py`, which is why today's trace showed no `requested_model`.
- **Acceptance**: pin unknown → 400; pin a cooled model → 200 with the header and the reason;
  pin a healthy model → identical header; a test drives all three through the real handler.

## B2 — Guard coverage and failure reporting

### #24 ENOMEM listing `/app/skills/pi-native` · env, M

- **Same class as today's verify failure**: `os.listdir('/work')` returning ENOMEM while the image
  filesystem was fine and 800 MB was still available in the VM. Diagnosis that held: probe an
  image-internal path (works) and a smaller mount (`scripts`, works) — a full mount listing fails.
  The operator confirmed the VM was simultaneously starting other containers in a second session.
- **What is ours to fix**: the failure mode, not the engine. (a) `verify.py` now streams the tree
  into the container when the mounted run dies with ENOMEM (`runner=docker(streamed)`, commit
  `1274f13`). (b) The orchestrator should treat a failed `listdir` as a transient condition: retry
  once after a short backoff, then fail with an error that names the remedy ("docker VM file
  sharing is unhealthy; restart Docker Desktop") instead of leaking a raw `OSError` into the
  dispatch result.
- **Acceptance**: a simulated ENOMEM (monkeypatched `listdir`) is retried once and then reported as
  `mount_unhealthy` with the remedy; the real path is unaffected.

### #19 Large-write guard bypassable via `codemode` · S

- **Reproduced 2026-11-24** and again today in a benign form: a 48-line doc write was blocked, and
  the only reason it stayed honest is that I split it. A `codemode` script calling `tools.write`
  is still invisible to the guard.
- **Plan**: the guard inspects the `codemode` call's script text; when it contains `tools.write(` or
  `tools.edit(`, apply the same line-count rule to the literal content argument it can see. If the
  content is computed (not a literal), warn once per session that the check cannot see it and log
  the call — partial coverage stated out loud beats silent coverage.
- **Acceptance**: a `codemode` call whose literal payload is 86 lines is blocked with the same
  message as a direct write; a computed payload produces the documented warning; both tested.

### #16 Write guard suggests tools absent from the session · S

- **Evidence**: the block message says "Run orchestrator.plan_task or dispatch_subagent(…)" even in
  sessions where those tools are not connected — exactly the situation that pushes an agent toward
  a lossy heredoc write (issue #14).
- **Plan**: build the suggestion from the session's actual tool list. Orchestrator present → keep the
  current text. Absent → "no review tool is connected in this session; say 直接做 to proceed, or
  split the write under 40 lines". Never suggest a path that cannot be taken.
- **Acceptance**: with the orchestrator MCP disconnected the message names only reachable actions;
  with it connected the wording is unchanged; both tested by stubbing the tool registry.

### #8 Exit-gate bounce truncates the failing test identity · S

- **Evidence**: the bounce showed an `assertRegex` frame but not the `ERROR: <test id>` header, so
  the agent had to re-run to learn which test failed.
- **Root cause**: `orchestrator/exit_gate.py` keeps a fixed tail (`text_tail` = last 200 chars in
  the audit record) and the bounce message inherits it.
- **Plan**: extract, in order: every line matching `^(FAIL|ERROR): `, then the last traceback frame,
  then the tail capped at 4 KB. Include the extracted ids in the bounce header line so the first
  line of the bounce is actionable.
- **Acceptance**: a fixture with 3 failing tests produces a bounce that names all 3 ids without
  reading the tail; a 100 KB output still yields a ≤4 KB message.

### #12 Failover dies on 400 / crashes on list payloads · stale, M

- **Current state**: `app.py` now treats `status_code >= 400` as "try the next candidate" (lines 759,
  1142) and the all-failed path returns 503 with the first real upstream error. What was not
  re-verified after the rewrite: non-dict JSON error payloads (a bare list) and whether a genuine
  400 (malformed request shape, which will fail on every upstream) should still walk the whole chain
  and burn 6 upstream calls.
- **Plan**: (a) defensive parse — any non-dict `error` becomes `str(payload)[:200]`, never an
  exception; (b) classify 400 as `client_error`: try one more candidate only if the candidates
  differ in protocol, then stop and return 400 with the upstream message, because repeating a
  malformed request against 7 upstreams is quota waste with no chance of success.
- **Acceptance**: list-shaped error payload → no exception, correct status; malformed-request test →
  at most one retry, HTTP 400 surfaced; genuine 429 chain → unchanged full walk.

## B3 — Dispatch architecture (the two issues that make sub-agents unreliable)

### #21 dispatch_subagent pins a whole run inside one MCP request · L

- **Evidence**: 5 concurrent sub-agents; three finished server-side at 63 s, 162 s and never, while
  the client had already reported `MCP request timed out after 60000ms`. The finished results were
  unreachable and the quota was spent.
- **Root cause**: one long-running call is the only interface; there is no handle to come back to.
- **Plan**: split into three tools. `dispatch_subagent` returns `{task_id}` immediately (always
  async; the old synchronous behaviour is kept behind an explicit `wait=true` for callers that want
  it). `dispatch_result(task_id)` returns `running|done|failed` plus the report. `dispatch_cancel`
  stops a run and releases its slot. Results persist to `traces/dispatches.jsonl` first, so a client
  restart still finds them; the MCP layer becomes a reader, not the owner of the result.
- **Migration**: existing call sites that relied on the return value get `wait=true` semantics for
  one release, with a deprecation note in the tool description; the controller prompt is updated in
  the same commit so new work uses the handle.
- **Acceptance**: 5 concurrent long tasks → 5 immediate `task_id`s, no client timeout, every result
  retrievable, quota accounted once; a cancelled task leaves no running process.

### #7 dispatch_readonly / dispatch_tooled cannot reach host worktrees · L

- **Evidence**: `workdir=D:\MyWorkSpaces\tmp\…` → `not a directory: .`; `dispatch_tooled` →
  `pi binary not found (tooled sub-agents run host-side only)`.
- **Root cause**: the orchestrator lives in the backend container with selective mounts, so the host
  filesystem is simply not there. Mounting the host tree into the gateway would trade a convenience
  for a security surface that the architecture deliberately avoided.
- **Plan**: make the boundary explicit instead of accidental. Read-only work on host paths goes
  through a small host-side agent (`scripts/host_dispatch.py`) that the MCP tool calls over the
  loopback port it already uses; the container never gets a host mount. When that agent is absent,
  the error names the boundary and the remedy rather than leaking an `ENOENT`.
- **Acceptance**: a dispatch against a host path succeeds through the host agent and records
  `runner=host`; with the agent stopped the error is `host_dispatch_unavailable` plus the command to
  start it; no new mount appears in `docker-compose.yml`.

## B4 — Verification plane

### #13 Experiment workloads have no container plane · M

- **Current state**: every lab record says `runner=host`; arms A–D talk to `:8788` on the host
  loopback and arm A0 reads provider keys from the repo `.env`. The deviation is declared in each
  record (which is why it was auditable today) but never fixed.
- **Plan**: run `experiments/runner.py` inside the lab container (`docker compose -f
  docker-compose.lab.yml run --rm lab-runner python experiments/runner.py …`), writing results to a
  mounted `experiments/runs`. A0 keeps its direct-provider path but reads `SILICONFLOW_API_KEY` from
  the lab env, not from `.env`. `HARNESS_RUNNER` is set by the entrypoint so the field states the
  truth without the caller remembering.
- **Acceptance**: a campaign cell launched through compose records `runner=container` and its
  network calls originate from the container (verified from the gateway's access log); no host
  python is involved; the same cell re-run on the host is refused or clearly labelled.

### #9 `run_gate` executes caller commands inside the backend container · M

- **Evidence**: `python tests/test_plane_alignment.py` → `No such file or directory` at `/app`;
  verdict `no_evidence` even for a command that passes on the host.
- **Root cause**: `verification_commands` inherit the orchestrator's execution plane, which has
  selective mounts only, so a verdict about "this repo" is produced from a tree that is not this
  repo.
- **Plan**: route caller commands to the sandbox runner (`scripts/verify.py --runner docker`, the
  same one the exit gate uses) and name the runner in the verdict. Refuse — rather than silently
  mis-evaluate — when the command references a path outside the mounted tree.
- **Acceptance**: `run_gate` with a repo test path returns a real verdict with `runner=docker`; a
  command touching an unmounted host path returns `plane_mismatch` with the reason.

### #10 Cap normalization drags L2 conclusions to L4 · stale, S

- **Evidence**: repeated transport notes `头部 Confidence Cap L2 与正文最弱依据 L4 不一致, 归一为 L4`.
- **Root cause**: normalization takes `min()` over every layer mentioned, and L4 (intent/resource
  constraints) sits below L2 in that ordering. An intent constraint is a dependency, not weaker
  evidence.
- **Plan**: exclude L4 from the min() (and keep L5 computed from upstream evidence only); keep the
  current behaviour of logging the computed cap to the trace. Unknown/absent layer → keep the
  declared cap and note why.
- **Acceptance**: a reply with L2 evidence plus an L4 constraint keeps `Confidence Cap: L2`; a reply
  whose weakest *evidence* is L3 still normalizes to L3; both tested.

### #6 Contract intercept demands three-part structure for Tier 0/1 · stale, S

- **Evidence**: a Tier 0 version query was bounced with `缺少三段式锚点`. Note this is the twin of
  closed #15 (quoted-phrase false positive): same interceptor, different rule.
- **Current state**: today's Tier-0-ish mechanical replies still carry the three-part skeleton out of
  habit, so the defect is masked rather than fixed — the interceptor's rule was never re-read after
  the contract was compiled.
- **Plan**: read the tier from the reply's own tag and apply the structure rule only for Tier ≥ 1.5;
  for Tier 0/1 require the tag plus a non-empty body. Unknown tier → warn once, do not bounce.
- **Acceptance**: a Tier 0 reply with a one-line answer passes; a Tier 1.5 reply without anchors
  still bounces; both tested against the real interceptor.

### #5 `harness_version.py` reports "aligned" for a stale contract · S

- **Evidence**: the script printed `all planes aligned` (exit 0) while the live pi session was running
  an older compiled contract; a missing stamp was skipped instead of counted.
- **Root cause**: "loaded" is read from a file the script chooses rather than from the plane that the
  session actually loads, and absent stamps are treated as "nothing to compare".
- **Plan**: compare three planes explicitly — spec (`harness.yaml`), installed (`~/.pi/harness`),
  and loaded (the `AGENTS.md` under `~/.pi/agent` plus its stamp) — and print a table with a verdict
  per plane. A missing stamp is `unknown` and makes the exit code non-zero, because "I cannot tell"
  is not "aligned".
- **Acceptance**: after editing `harness.yaml` without re-installing, the script exits non-zero and
  names the stale plane; with everything installed it exits 0; a deleted stamp yields `unknown`,
  not `aligned`.

## B5 — Closures and monitoring (no code, or code that already exists)

### #18 Gemini tool calls 400 on missing thought_signature · stale, M

- **State**: the store plus `_attach_thought_signatures` landed (`d7bdb38`); synthetic replays (8
  variants, both Google models) all returned 200, so the fix has never been exercised by a real
  failure. Google is also out of every chain since then, so the blast radius today is zero.
- **Plan**: keep the fix, close the issue as *dormant with a monitoring rule* rather than "fixed":
  re-entry into a chain requires a replay through the recorded failing turn (kept in
  `traces/failed_requests/`). Trigger to reopen: any new `missing a thought_signature` in traces.
- **Acceptance**: the replay harness reproduces the 400 on the archived turn and passes with the fix;
  until then the issue stays labelled `dormant`.

### #17 zcode fingerprint harvesting · wontfix

- **Decision recorded (issue #17 comment)**: the reverse-proxied agent was identified by the vendor
  from its system prompt; off-peak quota and the 1.5× multiplier were withdrawn. The
  `client_fingerprint` mechanism stays in `quota_policy.yaml` unused. No further work.

### #14 bash heredoc halves backslashes on the Windows host · env/upstream

- **Class**: pi's bash tool on Git Bash, not our code. Filed upstream (`badlogic/pi#9` covers
  `cmd is not defined`; the heredoc escaping is the same tool).
- **Our rule until it is fixed**: never write code through a quoted heredoc; use the write tool, and
  when a write is blocked by the guard, split it — today's session showed both failure paths still
  bite.
- **Acceptance for closure**: upstream reproduces and fixes; our operator rule is already in the
  contract and needs no further work.

### #4 Minimum sufficient cause gate · stale

- **State**: adopted into the contract (section 2, "Minimum Sufficient Cause Check") after the
  devmap-64 incident, with scope, counter-examples and an audit_dag soft warning.
- **Plan**: close with a pointer to the contract section plus the golden-case replay directory
  (`evals/minimum_sufficient_cause/`) so the behaviour is verifiable rather than promised.

## Cross-cutting themes

1. **Truth of the catalog is one fact stored in two places.** #22 and #23 are the same defect seen
   from the router and the client: models are declared in `quota_policy.yaml` while routability lives
   in the chains. Fix both by generating the client catalog from the chains.
2. **The environment fails in ways our code reports as *our* bug.** #24 and today's verify failure
   produced 18 red tests and one failed dispatch, all from a file-sharing layer returning ENOMEM.
   The durable fix is a cheap probe plus a named remedy, not a retry loop that hides it.
3. **Dispatch is synchronous where it must be asynchronous, and container-bound where it must reach
   the host.** #21 and #7 are one design question: what is the contract between the container and the
   worktree? Answer it once, in B3, not twice.
4. **Guards that cannot see themselves.** #19 (codemode bypass) and #16 (suggests absent tools) are
   both about a guard whose model of the session is incomplete. State the boundary out loud when it
   cannot be enforced.

## Execution calendar (relative to today)

| When | Batch | Why this order |
|---|---|---|
| Today, next session | B1: #25, #11, #23, #22 | Small, and they decide whether the router and the git history can be trusted at all |
| Following day | B2: #24, #19, #16, #8 | Guard honesty and failure reporting; all S except #24 |
| Then, one block | B3: #21, #7 | Architectural; needs a design note before code |
| Then | B4: #13, #9, #10, #6, #5 | Verification plane; #13 unblocks honest experiment records |
| Close-outs | B5: #18 (dormant + monitor), #17, #14, #4 | Decisions already made; they need paperwork, not code |

## Rules for closing anything on this list

- A fix ships with the check that fails before it and passes after. No issue closes on "looks right".
- Environment-class issues (#24) close only with: the exact reproduction, the probe that separates
  environment from code, and the remedy line a human can act on.
- Anything re-verified as already fixed gets a comment with the evidence and is closed the same day;
  an issue left open "just in case" is a lie about the current state.
- Re-entry conditions are written down (e.g. #18) so a dormant issue cannot be mistaken for a fix.

<!-- END -->
