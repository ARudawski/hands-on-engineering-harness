---
description: Shared workflow routing, task records, authorization and evidence.
applyTo: '**'
---

# Hands-on Engineering Harness

Use the selected skill's stages. Do not start a full workflow merely because its topic matches. Load applicable repository/module guidance and required skills before dependent work; reuse unchanged contents. Missing guidance or access blocks only dependent work.

## Routing

| Need | Use |
| --- | --- |
| Resolve material decisions | `clarify-scope` |
| Record agreed scope | `write-spec` |
| Plan a feature through approved Linear publication | `plan-feature` |
| Divide agreed work into verifiable outcomes | `plan-slices` |
| Independent planning assessment | `plan-reviewer` |

## Task records

Resolve the active Git worktree root. Keep notes and evidence in `.tmp/<ticket-or-task>/`, excluded from commits, and reuse that directory. `index.md` contains only links with short descriptions. Keep scope, non-goals, ACs, decisions, checks, approvals, execution state and next action in `spec.md`. Keep records concise and link larger evidence. Source edits/build outputs stay in project locations.

Preserve IDs, decisions, approvals and evidence when resuming or migrating older records. Approved requirements and accepted durable decisions form the baseline; link the task delta without imposing a new specification framework. Identify any shared canonical revision and treat local notes as its working copy.

## Authorization and evidence

Planning alone authorizes task records. Implementation, commits, pushes and external publication need their own scoped authorization. Follow the selected workflow's approval gates and reuse existing authorization within its scope. Reused evidence grants no new authorization. Preserve unrelated edits and consumer settings.

Use configured integrations and actual tool schemas; discover project conventions rather than inventing required fields. Keep credentials out of records. Separate observed behavior, assumptions, planned checks, results and human acceptance. Identify assessed scope/revision, bound retries and recheck affected evidence after changes. Report gaps; do not treat static output or an empty review as runtime proof.
