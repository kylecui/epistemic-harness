# Related work (paper §2 source)

> Retrieval dates noted inline. arXiv items via export.arxiv.org API;
> OmO items via depth-1 clone + ripgrep of the repo and its CHANGELOG
> (2026-11-22). Every entry must carry a URL/PR ID + date read — unanchored
> superlatives are contract violations under this repo's own research
> discipline.

## 1. Claim detection and evidence binding in agent tools

- **OmO claim receipts (primary competitor / key citation).**
  oh-my-openagent, 71,050★, actively maintained (pushed 2026-11-22).
  - PR #10785: turn-final "tests pass / done" claims checked against a
    session check that passed after the last code edit; claim recorded as
    backed/unbacked. **Shipped in shadow mode** — the changelog states one
    week of internal sessions produced mostly false-positive flags; a nudge
    note and gate reviewer activate only behind `omo-senpi-claim-receipt-nudge`.
  - PR #11794: `bun check` accepted as type-check evidence.
  - PR #11542: argv echo no longer earns a test receipt.
  - PR #12832: ulw-research mandates `OBSERVED:`/`PROBED:` claim tagging.
  - PR #11046: machine-readable fact ledger / claim index for reports.
  - #7080: parent-side verification directive ("treat the claim as false
    until proven").
  Read 2026-11-22 (clone + `rg "claim" CHANGELOG.md`). Stored as
  knowledge/l2_library/evidence.yaml `L2-OMO-001`. Our differentiation:
  blocking enforcement vs shadow detection; measured near-zero FP on
  adversarial suites vs self-reported majority-FP; verifier-fingerprint
  tamper detection; failure-class attribution; broader claim surface
  (quantified/completeness/structural/tier).

## 2. Confidence calibration (why self-reported confidence is not enough)

- "Calibrating the Confidence of Large Language Models by Eliciting
  Fidelity" (arXiv, retrieved 2026-11-22 via arXiv API search) — confidence
  elicitation should measure fidelity, not verbalized certainty.
- "Confidence Calibration in Large Language Models" (arXiv, same retrieval).
  Reading: supports our design choice to never trust the model's declared
  tier — caps are computed deterministically from cited sources (weakest-link
  min), not from self-assessment.

## 3. Self-verification limits

- "A Closer Look at the Self-Verification Abilities of Large Language Models
  in Logical Reasoning" (arXiv, retrieved 2026-11-22).
- "Solving Challenging Math Word Problems Using GPT-4 Code Interpreter with
  Code-based Self-Verification" (arXiv, retrieved 2026-11-22).
- Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement
  Learning" (arXiv, retrieved 2026-11-22).
  Reading: self-verification degrades exactly on hard problems; our exit gate
  substitutes external deterministic checks for self-judgement.

## 4. Process supervision / verifiable rewards

- "Verifiable Process Rewards for Agentic Reasoning" (arXiv, 2026-11-22).
- "MAS-ProVe: Understanding the Process Verification of Multi-Agent Systems"
  (arXiv, 2026-11-22).
- "Lean4AgenticRL: Advancing Agentic RL with Verifiable Multi-level Process
  Rewards" (arXiv, 2026-11-22).
  Reading: process-level verification is an active RL line; our work is the
  governance/runtime dual — same "verify the process" insight, applied as
  infrastructure rather than reward shaping.

## 5. Agent memory (scope-limit for our memory claims)

- "Graph-based Agent Memory: Taxonomy, Techniques, and Applications"
  (arXiv, 2026-11-22).
- arXiv:2611.22179 "RAG in a Trenchcoat: When Minimal Memory Is Enough for
  Agentic Systems, and When It Isn't" (verified exists 2026-11-22; BRIDGE:
  minimal BM25+cosine memory reaches parity on LongMemEval-S / BEAM; their
  adversarial probes show no architecture wins universally). Basis for our
  E3 behaviour-over-hit-rate methodology.

## 6. Dual-process framing (honest demotion)

- "DualRAG: A Dual-Process Approach to Integrate Reasoning and Retrieval"
  and "MemDuet: Learning Dual-Process Memory for Long-Context Reasoning"
  (arXiv, 2026-11-22).
  Reading: dual-process in LLM literature is analogy, not measurement. Our
  "tiers" are routing labels over reasoning-effort parameters; the paper must
  NOT claim a cognitive model (reviewers would falsify it in one question).
