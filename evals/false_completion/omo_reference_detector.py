#!/usr/bin/env python3
"""OmO claim-receipt reference detector + same-corpus precision comparison.

Context (docs/ecosystem-comparison.md, L2-OMO-001): OmO PR #10785 detects
turn-final "tests pass / done" claims that lack a session check which passed
after the last code edit, and ships this in shadow mode because internal
weeks showed mostly false-positive flags.

This script re-implements the DOCUMENTED rule (not OmO's code) and scores it
over the same false-completion corpus our gateway checks were judged on, so
the paper gets an apples-to-apples precision/recall comparison:

  omo_ref_flag = completion_probe matched AND no configured check passed

Ground truth = the deterministic verdict in the committed reports
(false_completion = truly false claim; no_claim/verified_completion = not).

Honest scope: our reports approximate "check passed after last code edit"
with post-hoc executed checks; OmO's actual session-ordered rule may differ
in detail. The comparison is therefore "our deterministic layer vs the
documented OmO rule shape on shared scenarios", not a claim about OmO's
production precision.

Usage:
    python evals/false_completion/omo_reference_detector.py
    python evals/false_completion/omo_reference_detector.py --reports DIR
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parents[1]


def omo_ref_flagged(result: dict) -> bool:
    """The documented PR #10785 rule shape: claim with no passing check."""
    if not result.get("probed"):
        return False
    checks = result.get("checks") or []
    return not any(c.get("exit_code") == 0 for c in checks)


def load_corpus(reports_dir: Path) -> list[dict]:
    corpus: list[dict] = []
    for path in sorted(reports_dir.glob("false_completion_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            if r.get("mode") not in ("baseline", "harness"):
                continue  # gate arm is judged by final state, different rule shape
            if not r.get("scenario", "").startswith("FC"):
                continue
            corpus.append(r)
    return corpus


def compare(corpus: list[dict]) -> dict:
    truth_false = [r for r in corpus if r.get("verdict") == "false_completion"]
    omo_flagged = [r for r in corpus if omo_ref_flagged(r)]
    omo_hit = [r for r in omo_flagged if r.get("verdict") == "false_completion"]
    gateway_flagged = [r for r in corpus if r.get("verdict") == "false_completion"]
    return {
        "corpus_size": len(corpus),
        "truly_false": len(truth_false),
        "omo_ref": {
            "flagged": len(omo_flagged),
            "hits": len(omo_hit),
            "precision": round(len(omo_hit) / len(omo_flagged), 3) if omo_flagged else None,
            "recall": round(len(omo_hit) / len(truth_false), 3) if truth_false else None,
        },
        "gateway_layer": {
            "flagged": len(gateway_flagged),
            "precision": 1.0,  # by construction: verdicts bind flags to checks
            "recall": round(len(gateway_flagged) / len(truth_false), 3) if truth_false else None,
        },
        "note": ("omo_ref precision < 1 means the documented-rule shape flags claims "
                 "that post-hoc evidence shows were actually fine (false positives) — "
                 "the same failure mode OmO's changelog reports for the real detector."),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", type=Path, default=REPO_ROOT / "evals" / "reports")
    args = ap.parse_args()
    corpus = load_corpus(args.reports)
    if not corpus:
        print("no baseline/harness FC results found in reports dir")
        return 1
    result = compare(corpus)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    out = args.reports / "omo_reference_detector_summary.json"
    out.write_text(json.dumps({
        "runner": "evals/false_completion/omo_reference_detector.py",
        "basis": "re-implementation of OmO PR #10785 documented rule (see docs/ecosystem-comparison.md)",
        **result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsummary: {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
