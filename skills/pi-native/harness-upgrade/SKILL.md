---
name: harness-upgrade
description: "Upgrade the epistemic harness to the current repo version. Use when the user says 升级, upgrade, 发版, or asks to update the harness."
---

# Upgrade an existing harness installation: preview migrations, backup, migrate idempotently, rebuild containers, verify, stamp

> Global install precheck: the scripts below live in the harness global install,
> NOT in this skill directory and NOT in the working directory.
> If the precheck fails, run `python <harness-repo>/scripts/install_global.py`,
> then restart pi. Do NOT search the filesystem for the scripts.

```bash
# precheck — fail loudly with the fix, never wander:
test -f "{{HARNESS_HOME}}/scripts/harness_version.py" || { echo "harness global install missing: run scripts/install_global.py from the harness repo, then restart pi"; exit 1; }
```

Run from the harness REPO checkout (git pull happens there):
```bash
cd <harness-repo>
git pull
python scripts/upgrade.py --check   # preview
python scripts/upgrade.py           # backup -> migrate -> rebuild -> verify -> stamp
```
Rollback on failure: restore the printed `.upgrade-backup-<ts>/` dir. Host-only: `--no-docker`. Doc: docs/UPGRADE.md.
