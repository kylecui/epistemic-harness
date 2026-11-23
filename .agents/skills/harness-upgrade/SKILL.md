---
name: harness-upgrade
description: "Upgrade an existing harness installation: preview migrations, backup, migrate idempotently, rebuild containers, verify, stamp. Use when the user says 升级, upgrade, 发版, or asks to update the harness."
---

# Upgrade the epistemic harness to the current repo version

Run from the repo root:
1. `git pull`
2. `python scripts/upgrade.py --check`   # preview: installed -> spec, pending migrations
3. `python scripts/upgrade.py`           # backup -> migrate -> rebuild -> verify -> stamp

Rollback on failure: restore the printed `.upgrade-backup-<ts>/` dir over the repo.
Host-only machines: add `--no-docker`. Authoritative doc: docs/UPGRADE.md.
