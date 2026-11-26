# Branch model

Four roles, one rule each. Written 2026-11-26 after the audit found `master` on v0.5.2 while v0.5.4 had
been released on the development line — the default branch was two releases behind.

| Branch | Role | Rule |
|---|---|---|
| `master` | latest stable | only releases and hotfixes land here; always shippable |
| `dev` | integration | features and fixes merge here first; releases are cut from it |
| `hotfix/<ver>-<topic>` | urgent fix on the stable line | branched **from the last release tag**, never from `dev`; commits are cherry-picked to `master` **and** back into `dev` |
| `paper/<n>-<topic>` | one branch per paper | research artifacts and measurements only; code found while writing goes to `hotfix/` or `dev`, never here |

## Why hotfix starts at the tag, not at master

`master` moves only by release and hotfix, so a hotfix branched from it sits one commit from what users
run. Branching from `dev` would carry unreleased work into a "fix" and make the cherry-pick a merge in
disguise. If a backport does not apply cleanly, that is information: the fix depends on unreleased code,
so it belongs on `dev` instead.

## Cherry-pick rule

A hotfix commit is applied to `master` first (that is what ships), then cherry-picked into `dev` with
`-x` so provenance is visible. When the reverse order is easier, say so in the commit message and name
the equivalent commit on the other line — silent divergence is the failure this model prevents.

## Layout (2026-11-26)

| Branch | Head | Content |
|---|---|---|
| `master` | v0.5.4 + `hotfix(router)` | blue/green router backport on the released line |
| `dev` | `research(m1): the full anchored pass` | the whole 2026-11-25/26 issue sweep plus the campaign and its measurements |
| `hotfix/v0.5.5-router` | same commit as master's hotfix | the backport itself, kept for provenance |
| `paper/1.5-interim-contracts` | from `dev` | interim schema + guard + subagent report |
| `paper/2-reasoning-ledger` | from `dev` | mode enforcement, ReasoningRecord ledger, L5 claims |
| `paper/3-format-vs-outcome` | from `dev` | the A0–D campaign and the three M1 measurements |

Retired branches (`feat/structured-interim-p1`, `research/structured-interim-contracts`,
`fix/contract-false-positives`, `fix/intercept-dedup`, `fix/issues-2026-11-25`) hold history already
contained in `dev`; keep them read-only for provenance.
