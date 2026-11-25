# gated_commit ignores selective staging: `git add -A` sweeps every change into one commit

## What happens

`scripts/gated_commit.py` runs `git add -A` before `git commit`. A caller that staged
specific paths (`git add scripts/verify.py tests/test_foo.py`) to make a focused commit
still gets every other modification in the working tree swept in.

Observed on 2026-11-25: I staged two files for a `fix(verify)` commit; the resulting
commit `1274f13` also carried `Dockerfile`, `docker-compose.yml`, both READMEs, the
experiment scripts and 30 data files. The message describes less than the diff does,
which is exactly the kind of history that makes a later `git log -S` useless.

## Why it matters

- Commit messages stop matching their diffs, so bisecting and archaeology get harder.
- A long-running experiment writes data files continuously; every unrelated commit
  becomes a data checkpoint nobody asked for.
- There is no way to express "commit only this" through the gated path, which pushes
  people toward bypassing the gate for small commits.

## Reproduction

```
git add scripts/verify.py
python scripts/gated_commit.py -m "fix(verify): ..."
git show --stat HEAD | head    # unrelated files are in the commit
```

## Suggested fix

Honour a selective index: if `git diff --cached --name-only` is non-empty, commit only
what is staged (`git commit` without `add -A`); otherwise keep today's `git add -A`
behaviour for the common case where the caller stages nothing. Print which mode was
used, so the log says whether the commit is selective or a sweep.

## Acceptance

- Staged-only run: unrelated modified files stay out of the commit and remain in the
  working tree; `git show --stat HEAD` lists exactly the staged paths.
- No staged files: unchanged behaviour (`git add -A` then commit), still green-gated.
- Test covers both modes without touching the real repository history.
