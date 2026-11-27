# Paper 2 §7 — the reasoning ledger: information-flow closure instead of trust

The claim this section defends: an agent's epistemic labels are only worth enforcing if the *order* in
which evidence and claims were produced can be checked. A record that cites evidence it could not have
seen yet is not weakly-evidenced — it is fabricated, and the ledger must refuse it.

## The record

`contracts/schemas/reasoning-record.schema.json` requires exactly: `schema`, `record_id`, `tier`,
`mode`, `claims`, `evidence_refs`, `open_gaps`, `ts`. Nothing about prose, nothing about length. The
model declares what it concluded and which evidence it used; the ledger checks those declarations
against its own state.

## The check: closure, not plausibility

`orchestrator/reasoning_ledger.py::submit_record` applies three rules in order and rejects on any of
them — a rejected record is **not written**, so the ledger stays append-only and trustworthy:

1. **Schema validation** of the record itself.
2. **Timestamp parseability**: epoch or ISO-8601, or the record cannot take part in ordering at all.
3. **Information-flow closure**, the substantive one. For every `evidence_refs` entry and every
   `claims[i].source_ids` entry, the referenced evidence must already be registered *and* carry a
   timestamp strictly earlier than the record's:

```
f"{where}: {ref} not registered (forward reference or unknown)"
f"{where}: {ref} ts {ev['ts']:.3f} >= record ts {ts:.3f} (information-flow violation)"
```

That second message is the mechanism: a claim that cites evidence produced at or after its own timestamp
is a forward reference. It is the machine-checkable form of "you could not have known that yet", and it
catches the failure mode prose review misses — a confident conclusion whose cited support was written
afterwards, or never existed.

Duplicate `record_id` is rejected too, so the ledger cannot be rewritten by replaying an id.

## Why this is enforcement rather than another prompt

* **State lives outside the model.** Evidence is registered by the harness when a tool output arrives
  (`register_evidence`), not when the model says so. The model cannot bootstrap its own support.
* **Rejection is silent-free.** `{"ok": false, "violations": [...]}` names the offending reference and
  the two timestamps, so a controller can act on it without guessing.
* **It composes with the other layers.** The exit gate binds *which check* backs a claim; the ledger binds
  *whether the support existed first*; the interim schema binds *the shape* a sub-agent report must have.
  Three different questions, three deterministic answers, no overlap.

## What it does not do

* It cannot tell whether the cited evidence actually supports the claim — that remains a judge's job, and
  Section 6 shows how unreliable judges currently are. Closure is necessary, not sufficient.
* It does not police prose outside records: a model that never files a record is caught by the exit gate's
  claim-binding rule, not here.
* It assumes a single monotonic clock per ledger. Two machines writing with skewed clocks would produce
  spurious violations; the campaign and the orchestration plane run in one container today.

## Evidence in this repository

* `tests/test_reasoning_ledger.py` — closure rejection (forward reference, unknown reference, duplicate
  id), acceptance of a well-ordered record, and the status report.
* `contracts/schemas/reasoning-record.schema.json` — the required-field set quoted above.
* `orchestrator/reasoning_ledger.py` — `register_evidence` / `submit_record` / `ledger_status`, all
  exposed through the MCP server so a controller can file and check without trusting the model.
