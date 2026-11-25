# Router operations: blue/green, upgrade, rollback (2026-11-25)

This file replaces every earlier instruction that said `docker compose up -d --build` for the
router. That command is what took the only exit down: an upgrade rebuilt the serving container,
baked a working tree whose `orchestrator/exit_gate.py` had a SyntaxError, and pi answered every
turn with `connect ECONNREFUSED 127.0.0.1:8787` until someone rebuilt it by hand.

## Topology

```
pi ──► 127.0.0.1:8787  router-gate        (owns the port pi already holds)
        ├─► backend-blue   127.0.0.1:8789 (one of these is active)
        └─► backend-green  127.0.0.1:8790 (the other is idle = the upgrade slot)
```

* The gate probes both backends every 2 s. If the active one refuses a connection, the SAME request
  is retried once against a healthy spare, and the spare becomes active (`/__gate/status` records it).
* `harness-backend` (the single-container service) is now behind the `solo` profile. A plain
  `docker compose up` no longer starts it, because it would fight the gate for 8787.

## Upgrade (no client-visible interruption)

```bash
python scripts/router_build.py        # build :staging, IMPORT IT inside the image, then promote
docker compose -f docker-compose.yml -f docker-compose.ha.yml up -d backend-green
python scripts/router_switch.py switch green
docker compose -f docker-compose.yml -f docker-compose.ha.yml up -d backend-blue   # rebuild idle side
```

Why each step is not optional:

1. `router_build.py` refuses to move `:local` when the image cannot import `orchestrator.server`,
   `proxy_gateway.app` or `harness_backend`. The old image is kept as `:prev`. **Without this step a
   syntax error becomes an outage** — that is the whole point of the gate.
2. Starting the idle side lets it come up (and pass its health probe) without touching the serving
   side.
3. The switch is atomic from the client's view: 8787 never closes.
4. Rebuilding the now-idle side keeps both on the same image for the next upgrade.

`python scripts/upgrade.py` does the same thing automatically: it calls `router_build.py`, then
recreates the **idle** backend and switches to it (or, with no gate running, recreates the single
service under the `solo` profile). The plan it follows is unit-tested in `tests/test_upgrade_plan.py`.

## Rollback

```bash
python scripts/router_switch.py switch blue      # one command, seconds, no rebuild
```

If the promoted image is itself at fault: `docker tag epistemic-harness-backend:prev
epistemic-harness-backend:local`, recreate the idle side, switch.

## Do not

* Never run `docker compose up -d --build` (or `--force-recreate`) against the backend that is
  serving. Upgrade the idle one and switch.
* Never point pi at a container port (8789/8790). Only 8787 is a client contract; containers are
  replaceable, the port is not.
* Never promote by hand-tagging an image that has not passed `router_build.py`'s import gate.
* Solo mode (no gate) is allowed on a single-purpose machine: `docker compose --profile solo up -d
  harness-backend` — but then an upgrade is a visible outage, so say so before doing it.

## When something is already broken

| Symptom | First check | Fix |
|---|---|---|
| `ECONNREFUSED 127.0.0.1:8787` | `docker ps --filter name=router-gate` | start the gate, then `router_switch.py status` |
| Gate up, requests failing | `python scripts/router_switch.py status` (`healthy`) | switch to the healthy side; investigate the bad one with `docker logs harness-backend-<name>` |
| Both backends unhealthy | `docker logs harness-backend-blue` | if the image is broken: retag `:prev` → `:local`, recreate, switch |
| Image will not start | `docker run --rm --entrypoint python <image> -c "import orchestrator.server"` | rebuild via `router_build.py` (the import gate names the failing module) |
