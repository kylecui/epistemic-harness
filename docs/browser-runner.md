# Browser / CDP Placement Policy

> The question is not "container or host" — it is "what must stay identical in this task". CDP is a protocol interface: client and browser can live on different sides, so first decide what to pin, then decide where the browser goes.
> 中文辅助版见 git 历史；规范以本文为准。

## 1. Decision rule

| Scenario | Browser side | Why |
|---|---|---|
| Verifying self-hosted / local apps (compose-raised sites) | container | the target is inside the container network; `localhost` semantics agree; the user's real profile is untouched |
| Visual/behavioral baselines that must be byte-stable across machines | container | fonts, scale, and Chrome version are pinned together; no drift when machines change |
| The page must not see the user's cookies/login state | container | clean profile, disposable afterwards |
| Needs real login state, real egress IP, extensions, GPU codecs | host | containers lack these; headless/datacenter IPs may be blocked |
| Sites with anti-automation (fingerprinting, risk control) | host (headful) | container and headless fingerprints are easier to flag |
| Only want to isolate the "read a page" step | either — **attach over CDP** | `--remote-debugging-port=9222` on the side that already owns the browser; the agent stays put and only the endpoint changes |

One sentence: containerization wins when what must be reproduced is **our page and our baseline**; the host wins when what must be reproduced is the **real web's reaction**.

## 2. Evidence

- **Reproducible web environments are containerized**: WebArena's design goal is explicitly "highly realistic and reproducible", built on self-hosted functional sites (a dockerized stack) rather than the live internet. arXiv:2307.13854 — https://arxiv.org/abs/2307.13854 (read 2026-11-21)
- **The container browser is not for untrusted pages**: Playwright's own Docker doc states the image is for testing/development, **recommends against visiting untrusted websites** with it, and notes root disables the Chromium sandbox (scraping should use a separate user + seccomp). https://github.com/microsoft/playwright/blob/main/docs/src/docker.md (read 2026-11-21)
- **Sandbox mode needs extra privileges**: Puppeteer's Docker doc requires `--init` for child processes and `SYS_ADMIN` for sandbox mode. https://github.com/puppeteer/puppeteer/blob/main/docs/guides/docker.md (read 2026-11-21)

Together these draw the anti-"containerize everything" boundary: putting untrusted pages into a container browser yields "sandbox disabled + amplified privileges" — worse than the host.

## 3. Constraints on this machine (Windows + Docker Desktop)

- Containers live in the WSL2 VM: container `localhost` **is not** the host; use `host.docker.internal`.
- `/dev/shm` defaults to 64 MB and crashes Chrome under load: add `--shm-size=2g`.
- WebGL falls back to SwiftShader in containers → pixel results differ from host GPU → **baselines bind to the runner that produced them**.
- Publish the port (`-p 127.0.0.1:9222:9222`) and host processes can drive the container browser over CDP directly.

## 4. Standing conventions (written into artifacts, not memory)

1. Every visual/behavioral baseline records `browser_runner` (host|docker), browser version, viewport, and scale next to it.
2. Comparisons happen **within one runner**; cross-runner comparisons require re-baselining first.
3. CDP connection strings live in task contracts (`predicates[].check` pointing at the verification command), not in free text.
4. Untrusted pages do not enter the container browser: static fetch without JS execution, or an isolated-network read-only profile.
5. Container browsers run as non-root with `--no-sandbox` documented, or with `SYS_ADMIN` in a dedicated image when real sandboxing is required — the privilege escalation is recorded.

## 5. Relation to the overall execution substrate

Verification commands still go through `scripts/verify.py` (container-first). Browser tests are one class of check: they carry `runner` semantics, but the extra `browser_runner` dimension is recorded separately, because "the check ran in a container" does not imply "the page came from a container".

## 6. Acceptance

- Two screenshots of the same page within one runner differ by 0; a cross-runner diff > 0 is classified "baseline mismatch", not "page regression".
- With the container network cut, a container browser still reaches a self-hosted site (target inside the container network) and cannot reach external sites (no implicit host network).
