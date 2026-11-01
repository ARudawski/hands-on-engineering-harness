---
name: plan-feature
description: Plan a feature through reviewed specifications, ticket drafts and approved Linear publication.
---

# Plan a feature

Load applicable repository/module guidance and required skills. Reuse `<active-worktree>/.tmp/<task>/spec.md` and its navigation index. Link approved/accepted durable baselines and influential sources. Preserve decisions, IDs, approvals and evidence on resume.

After **each of stages 1–4**, present its result and next action, then end the turn for human approval. An earlier approval does not approve a later result. Stage 4 must explicitly request approval to publish the exact batch to its identified destination.

1. **Research.** Read the concept/ticket, relevant comments, existing specifications and affected code/tests/contracts. Discover available capabilities and overlapping work. Check consequential uncertainty early; report inaccessible evidence.
2. **Agree scope.** Use `clarify-scope` to resolve material decisions the sources cannot settle. Agree outcome, exclusions, constraints, observable acceptance and any accepted limitations before specification work.
3. **Specify and review.** Use `write-spec`. Obtain a fresh **`plan-reviewer`** assessment of the specification. Resolve material findings with that reviewer; scope/AC changes require user agreement. Present the reviewed spec for approval.
4. **Draft and review the batch.** Use `plan-slices` and [Linear guidance](references/linear.md). Map every AC to useful tickets or explicit existing work, with verification and real dependencies. Record the complete proposed payloads/destination in `tickets.md`, including a stable batch UUID/draft marker for each new resource. Identify a frozen snapshot or fingerprint. Obtain a separate fresh **`plan-reviewer`** assessment of that exact batch, coverage and dependencies; resolve corrections in the same session. Present the corrected batch and intended writes for publication approval.
5. **Publish and read back.** Only after exact-batch/destination approval, follow [publication and recovery guidance](references/linear.md). Recheck external state/capabilities; material changes require affected review and renewed approval. Write parents first, checkpoint returned IDs/operations immediately in `publication.md`, reconcile dependencies/links and read back the final resources. Report mapping, URLs, completion and gaps. Resume only missing approved operations after reconciliation; never duplicate an uncertain write.

Supply each reviewer the artifact/index, assessed revision, coverage, relevant sources/results and applicable guidance contents or readable paths. The child must establish its own required context; parent-only loads and unread paths are insufficient. No self-review or substitute role. Reuse valid assessments without reopening settled work; optional suggestions need no correction loop.

Missing reviewer/context leaves review incomplete. Unresolved scope, rejected/stale batches or missing write capability stop dependent publication. Planning grants no implementation, commit or push authority; publication approval covers only the exact approved writes.
