# Issue closes to retry — GitHub API returned GraphQL/502 on 2026-11-25 16:11Z

Closed already: #22, #6, #11.
Blocked by the API, not by the work. Retry each with the given comment:

| Issue | Commit | Comment |
|---|---|---|
| 25 | 8a75ad5 | gated_commit now commits the staged index when the caller staged anything and sweeps only when nothing is staged (`mode=staged (N paths)` / `mode=sweep`). Verified by the commit that carries the fix: it holds exactly two files while unrelated edits stayed in the tree. Two tests drive main() with a stubbed run(). |
| 24 | 93a97e1 | orchestrator/fsretry.py classifies ENOMEM/EIO/EBUSY/ESTALE as transient and retries once; ENOENT/ENOTDIR stay fatal. Applied at the read-only list_dir and the registry load; a spent budget returns a typed `mount_unhealthy` error naming the remedy (restart Docker Desktop) instead of leaking OSError. Retrying the whole dispatch was rejected: it would pay for a second model call to work around a filesystem blink. |
| 23 | 832d399 | The catalog generator now intersects model definitions with routing-chain membership (honouring `routable: false`). Installed catalog 16 -> 12 ids; the four copilot/google ids are gone from ~/.pi/agent/models.json while their definitions stay in quota_policy.yaml. |
| 21 | 239f527 | dispatch_subagent(wait=false) returns a task_id immediately and runs on a small pool; dispatch_result(task_id) reports running/done/failed with the report and elapsed time; unknown ids list the ones that exist. wait=true keeps the old behaviour. Tests: a 0.6 s fake dispatch returns a handle in under 0.5 s and polling observes running -> done. |
| 19 | bef04f2 | The guard branches on codemode, scans for tools.write/tools.edit, measures a literal payload against the 40-line threshold and blocks with the same message; a computed payload produces a once-per-session notice that its size cannot be checked. Runtime-assembled payloads remain invisible by construction and the notice says so. |
| 16 | bef04f2 | The block message is built from whether the orchestrator MCP server is present in mcp.json; absent, it says no planning tool is connected and offers only actions that exist. |
| 13 | 12b776d | runner.py and judge.py read HARNESS_LAB_GATEWAY (default unchanged), and docker-compose.lab.yml gains a `lab-runner` service on the campaign profile with HARNESS_RUNNER=container, so records state the plane themselves. Tests cover the env override and the compose contract. |
| 8 | 2baabef | A bounce now starts with the extracted FAIL:/ERROR: ids (then the last traceback frame, then at most 4 KB), so the first line names the failing test. |
| 5 | 045a117 | An unreadable session or repo contract is drift with the path and the fixing command, and the header pattern accepts the product's older name so a stale contract is reported by version instead of as unparseable. |
| 10 | n/a | Already fixed: weakest_body_layer() treats only L1-L3 as evidence inputs; reproduced that a body with L2 evidence plus an L4 constraint keeps `Confidence Cap: L2`. |
| 17 | n/a | Recorded decision: the fingerprint was obtained from the vendor's own open-source client, but using it drew quota the vendor withdrew once it identified the proxy, so the mechanism stays unused. |
| 4 | n/a | Adopted into the contract (AGENTS.md section 2, Minimum Sufficient Cause Check) with scope, counter-examples and an audit_dag soft warning. |

Still open with work remaining: #7 (host dispatch plane), #9 (run_gate plane), #12 (re-verify
failover semantics after the rewrite), #14 (upstream pi defect), #18 (dormant with a monitor),
#26 (someone else's), and the queued contract-intercept defect in
`.pi/pending-issues/issue-27-contract-intercept-on-subagent-reports.md`.
