# Upgrading an existing installation

> Applies from v0.4.x → v0.5.0 onward. Fresh machines use
> [INSTALL.md](INSTALL.md) instead.

## What the upgrade path must protect

An existing install carries state that a `git pull` alone would damage or
leave inconsistent:

| State | Location | Upgrade handling |
|---|---|---|
| Secrets | `.env` | never touched; backed up first |
| Exit-gate config | `.pi/exit_gate.json` | migrations **merge** into it, never overwrite |
| Knowledge stores | `knowledge/` (yaml + FTS5 db + l5_store) | yaml is additive (new fields have defaults); db rebuilt |
| Pending promotions | `promotions/pending_pr.yaml` | preserved |
| Compiled contract | `AGENTS.md` / `SKILL.md` | recompiled from `harness.yaml` |
| Containers | docker images | rebuilt + smoke-tested |

## Procedure

```bash
cd epistemic-harness
git pull
python scripts/upgrade.py --check      # preview: current -> target, pending migrations
python scripts/upgrade.py              # backup -> migrate -> rebuild -> verify
```

The script is **idempotent**: each migration records its id in
`.pi/upgrade_state.json` and never re-runs. Running it twice is safe.

Success criteria (all are executed by the script, not assumed):
backup copied → each migration reports its change note → `docker compose`
rebuild → `GET /health` answers → `unittest discover` is green →
`.pi/installed_version` stamped.

## Rollback

On failure the script exits non-zero and leaves the backup directory
(`.upgrade-backup-<ts>/`). Rollback:

```bash
# from the repo root
cp -r .upgrade-backup-<ts>/. .        # restores .pi/, knowledge/, .env, promotions/
git checkout <previous tag>          # restore code
docker compose up -d --build
```

On success the backup is removed unless `--keep-backup` was passed.

## Support tiers

| Install shape | Upgrade support |
|---|---|
| git clone + docker (full) | FULL — scripted path above |
| git clone, host-only runner (`--no-docker`) | FULL — pass `--no-docker` |
| pip-style / copied tree without git | LIMITED — migrations and verify run; rollback via your own copy of `.pi/` + `knowledge/` |

## Version detection

`.pi/installed_version` is written by the installer/upgrade. Installations
that predate the stamp (v0.4.x) are detected by the presence of
`.pi/exit_gate.json` and treated as 0.4.0, so all v0.5 migrations apply.
