---
description: Shared workflow routing, task records, authorization and evidence.
applyTo: '**'
---

# Hands-on Engineering Harness

Use the selected skill's stages. Do not start a full workflow merely because its topic matches. Load applicable repository/module guidance and required skills before dependent work; reuse unchanged contents. Missing guidance or access blocks only dependent work.

After substantial work, close the user-facing turn in plain language with what was accomplished and the next logical action or decision in the active workflow. A finding, check result or verified blocker also counts as progress. At every approval gate and work-package handoff, state what happens next; an approval request must name the exact action and scope it authorizes. Once the workflow is complete, say so. Keep the close brief and natural; an existing closing sentence can cover this, and routine clarification only needs its question.

## Routing

| Need | Use |
| --- | --- |
| Choose a skill or answer “what's next?” | `route` |
| Resolve material decisions | `clarify-scope` |
| Record agreed scope | `write-spec` |
| Plan a feature locally, with optional work-item publication | `plan-feature` |
| Divide agreed work into verifiable outcomes | `plan-slices` |
| Independent planning assessment | `plan-reviewer` |
| Deliver general or mixed computer work; route by the requested deliverable | `deliver-task` |
| Deliver a maintained software change | `deliver-code` |
| Implement authorized scope | `implement-slice` |
| Dispatch an independent change assessment | `review-code` |
| Independent implementation assessment | `code-reviewer` |

Use `route` for an ordinary next-step question even when the user gives no command. It returns advice about the current task; the selected workflow owns execution and approvals.

## Task records

Resolve the active project root: use its worktree root when applicable, otherwise the active project directory. Do not require or initialize a repository to keep records. Reuse `.tmp/<ticket-or-task>/`, kept out of published source/commits. `index.md` is navigation; `spec.md` holds scope, plan/IDs, decisions, approvals, evidence and next action. Keep ordinary records concise Markdown; structured files are for tools/tests that need them. Source/build outputs stay in project locations.

Preserve IDs, decisions, approvals and evidence when resuming or migrating older records. Approved requirements and accepted durable decisions form the baseline; link the task delta without imposing a new specification framework. Identify any shared canonical revision and treat local notes as its working copy.

## Authorization and evidence

Planning alone authorizes task records. Implementation, commits, pushes and external publication need their own scoped authorization. Follow the selected workflow's approval gates and reuse existing authorization within its scope. Reused evidence grants no new authorization. Preserve unrelated edits and consumer settings.

Ticket systems, VCS clients/repositories and hosting services are optional. Select actions only from explicit task/project requirements; configured connections alone select nothing. Use actual schemas/capabilities for selected tools. Missing selected access blocks dependent actions only; report them as pending, preserving approved destinations/identities. Reading a remote issue grants no write authority. Without VCS, use affected-file before/after evidence or another reproducible comparison when review requires it; missing essential comparison/reviewer/checks remains a blocker.

Before implementation, establish the comparison and separate pre-existing/unrelated edits. Capture before-content/path inventory when VCS is unavailable, then retain after-state evidence including added/deleted paths. Reconcile actual scope/changes, AC results/gaps, approvals and next action at transitions; include branch/base/review-request/CI state only when applicable.

Keep credentials out of records. Separate observed behavior, assumptions, planned checks, results and human acceptance. Identify assessed scope/revision, bound retries and recheck affected evidence after changes. Report gaps; do not treat static output or an empty review as runtime proof.
