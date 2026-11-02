# CSV preview — draft-1

## State and authorization

Task ID CSV-17. Research AP-1 and scope AP-2 were accepted by this fixture's test driver.
Stage 3 is interrupted after write-spec produced draft-1, before independent PLAN review.
The current spec is authoritative; any embedded index content is historical.
Next action: review this exact draft before corrections, then correct/recheck with the same reviewer.
Specification approval, implementation, tickets, commits and external writes remain unauthorized.

## Baseline and decisions

Required approved durable baseline: [Export contract C1](../../docs/export-contract.md).
D-1: add preview_csv(rows, limit=5) separately; keep export_csv unchanged.
D-2: first input row is header; limit counts data rows. Empty input returns an empty string.
D-3: accept nonnegative integer limits, reject invalid limits; zero is header-only.
D-4: one-shot iterators must retain the first omitted row for their caller.
The task delta adds preview; it does not replace or rewrite C1.

## Acceptance and planned checks

| ID | Acceptance | Planned verification |
| --- | --- | --- |
| AC-1 | Header plus at most limit data rows, default five; correct empty/header-only/zero behavior. | Compare parsed CSV outputs for short/long/empty/header-only inputs and zero/custom limits; reject invalid limits. |
| AC-2 | Do not consume the first omitted row of a one-shot iterator. | Check preview output on a list of eight rows. |
| AC-3 | Full export and C1 remain intact; no persistence, UI or dependencies. | Compare full-export output/source to baseline; inspect changed imports and calls. |

## Draft approach requiring assessment

Convert rows to list(rows), take the header plus the requested data-row slice, then
serialize that slice using the existing export_csv. The entire iterable is materialized.

## Evidence and limitations

E-17: [Existing source observation](evidence.md). No runtime or implementation checks ran.
External tracking was intentionally excluded from this local fixture. No review or spec approval exists yet.
