---
name: plan-feature
description: Plan a feature through reviewed specifications and an approved local plan, with optional work-item publication.
---

# Plan a feature

Load applicable repository/module guidance and required skills. Reuse `<project-root>/.tmp/<task>/spec.md` and its navigation index. Link approved/accepted durable baselines and influential sources. Preserve decisions, IDs, approvals and evidence on resume. A task description or local file is sufficient input; no ticket, repository, VCS client, hosting account or service connection is required.

After **each of stages 1–4**, present its result and next action, then end the turn for human approval. An earlier approval does not approve a later result. Default to a local plan. Select external actions only from explicit task/project requirements; connected tools or a remote issue as input grant no write authority.

1. **Research.** Read the concept/ticket, relevant comments, existing specifications and affected code/tests/contracts. Discover available capabilities and overlapping work. Check consequential uncertainty early; report inaccessible evidence.
2. **Agree scope.** Use `clarify-scope` to resolve material decisions the sources cannot settle. Agree outcome, exclusions, constraints, observable acceptance and any accepted limitations before specification work.
3. **Specify and review.** Use `write-spec`. Obtain a fresh **`plan-reviewer`** assessment of the specification. Resolve material findings with that reviewer; scope/AC changes require user agreement. Present the reviewed spec for approval.
4. **Plan and review.** Use `plan-slices`. Map every AC to useful local outcomes or explicit existing work, with verification, stable IDs and real dependencies. Keep a small plan in `spec.md`, linking a larger artifact only when useful. Obtain a separate fresh **`plan-reviewer`** assessment of the exact plan, coverage and interactions; resolve corrections in that session. Present the corrected plan for approval. If publication is selected, also follow [publication guidance](references/publication.md): include exact payloads/destination in this assessment and request explicit approval of those writes, within or after plan approval.
5. **Hand off.** Record approval and report the usable local plan, order, checks and remaining gaps. Local completion needs no remote IDs, batch UUID, ticket file or publication ledger. For selected publication, follow [publication and recovery guidance](references/publication.md) only after exact-batch/destination approval; report its actual results separately. A later publication request starts a fresh `plan-reviewer` assessment of its exact payloads before write approval; retain valid prior plan assessments. Resume that publication reviewer for corrections while its basis remains valid.

Supply each reviewer the artifact/index, assessed revision, coverage, relevant sources/results and applicable guidance contents or readable paths. The child must establish its own required context; parent-only loads and unread paths are insufficient. No self-review or substitute role. Reuse valid assessments without reopening settled work; optional suggestions need no correction loop.

Missing required reviewer/context leaves review incomplete. Unresolved scope or rejected/stale work blocks dependent actions. Missing unselected tools does not block local work; an unavailable selected action stays pending. Never silently drop a remote request, replace an approved destination/identity or claim complete delivery while requested work is outstanding. Planning grants no implementation, commit or push authority; publication approval covers only the exact approved writes.
