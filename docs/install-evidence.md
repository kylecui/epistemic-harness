# Install Test Evidence (2026-11-21)

Two real from-scratch installations, run exactly as a new user following the
README. Raw transcripts live in `evals/install-evidence/*.log` (committed).

## Environments

| | WSL (Ubuntu on Windows 11) | Remote (`kylecui@10.174.254.128`) |
|---|---|---|
| OS | Ubuntu (WSL2), glibc 2.39 | Ubuntu 22.04 VM, glibc 2.35 |
| Python | 3.12.3 | 3.10.12 |
| Docker | Desktop integration (present after VM reset; absent before) | none |
| Detected tier | LIMITED, then FULL | LIMITED |

## What passed

- Fresh clone + `install.py --check` → correct capability matrix on both hosts.
- WSL full install: exit 0 — venv, requirements, hooks, client compile, verify
  image build, memory index, smoke test (`12-wsl`/`14-wsl` logs).
- Remote install (after host fix): exit 0 — host-runner smoke test, 213 tests
  in 1.9 s (`23-remote-install-after-venv.log`).
- `sh scripts/hvx` on WSL: 213 tests in container, 2.9 s (`15-wsl-hvx-matrix.log`).
- LIMITED-support warning printed with the explicit limitation list on both hosts.
- Shell integration correctly deferred (`--with-shell` opt-in) on both hosts.

## Defects found by the tests → fixed

1. **`scripts/hvx` not executable after clone** (Permission denied, WSL):
   committed mode was 100644; now 100755. Evidence: `15-wsl-hvx-matrix.log`.
2. **venv failure dumped a raw traceback** (fresh Ubuntu lacks `python3-venv`):
   install.py now prints the exact package command per distro and exits 2.
   Evidence: `22-remote-install.log` (failure) → `23-remote-install-after-venv.log` (resolution: `sudo apt-get install -y python3.10-venv`).
3. **Key prompt skipped silently** in non-interactive shells: a visible note now
   says keys were skipped and how to provide them.
4. **LIMITED warning was Windows-centric** on POSIX hosts (mentioned cmd.exe in
   WSL): warning bullets are now shell-family aware.
5. **Shell integration offered a Windows PowerShell profile inside WSL**:
   shell targets are now OS-aware (no powershell target off-Windows).
6. **Capability matrix claimed Copilot 'ok' with no credentials** (fresh clone):
   auth-backed models now require the token file (`.secrets/github-copilot.json`)
   or an env var. Evidence: matrix output in `15-wsl-hvx-matrix.log`.
7. **`rev=unknown` inside the verify container** (git dubious-ownership):
   `Dockerfile.verify` sets `safe.directory '*'`; verified — container banner
   now prints the real rev.

## Environment notes (not product defects)

- `wsl.exe` piped invocations are flaky past ~60–120 s (WSAETIMEOUT); long
  installs should run detached inside WSL. This is a WSL/Windows behavior.
- Docker Desktop state can flip WSL between LIMITED and FULL across VM resets;
  detection handled both correctly.
