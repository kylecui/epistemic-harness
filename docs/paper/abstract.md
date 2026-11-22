# Draft abstract (working, EN — for venue submission)

LLM coding agents frequently claim completion without evidence — "all tests
pass", "everything is implemented" — and the cost lands on the user who
trusts the claim. We study this failure class in the only agent tool that
ships a detector for it at scale, and find it runs in shadow mode: the
maintainers report that most of its flags were false positives, so it records
but never blocks. We argue the gap between detection and enforcement is a
precision problem, not a lost cause, and close it three ways. First, we
expand the claim surface that can be checked deterministically: quantified
and completeness claims must bind to checks the gate executed in the same
turn; declared defects must ship falsifiable acceptance criteria and named
rollback mechanisms; heuristic-derived conclusions are hard-capped by
transitive weakest-link provenance with anti-laundering citation grounding.
Second, we enforce at the transport and tool layers rather than nudging.
Third, we evaluate with adversarial suites instead of anecdotes: our checks
flag 13/13 laundering attacks with 0/7 clean-claim false positives, and
10/10 hollow compliance replies with 3/3 solid plans passing. On 5-trial inducement experiments against a frontier model, the enforcement
layer halves false-completion rates on implementation tasks (80%→40%) where a
prompt-only contract leaves unverifiable-completeness claims unchanged
(40%→40%); adding the blocking exit gate — the configuration the incumbent
ships only in shadow mode — drives false completions to zero across all
scenarios (0/20), including the class no post-hoc layer could move. The same
models pass a strict prompt-only contract only 11/30 and 18/30 across trials
(two frontier families), and neither declares hard-axiom conflicts unprompted
(0/10) — demonstrating why deterministic enforcement rather than stronger
prompting is the right lever. Enforcement costs +3.8k input tokens and
~0.2 s per turn. All artifacts, suites and measurement reports are open and
committed.

~260 words. Target: NeurIPS/ICLR agent workshop; trim to 200 if the CFP
requires.
