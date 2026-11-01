---
name: plan-feature
description: Research a feature and run approval-gated specification planning with an independent reviewer.
---

# Plan a feature

This version ends at specification approval. Ticket drafting and publication are unavailable; do not continue into them under this workflow.

Load applicable repository/module guidance and required skills. Reuse `<active-worktree>/.tmp/<task>/spec.md` and its navigation index. Link approved/accepted durable baselines and influential sources. Preserve decisions, IDs, approvals and evidence on resume.

After **each numbered stage**, present its result and next action, then end the turn for human approval. Approval of an earlier stage does not approve the next stage's result.

1. **Research.** Read the concept/ticket, relevant comments, existing specifications and affected code/tests/contracts. Discover available capabilities and overlapping work. Check consequential uncertainty early; report inaccessible evidence.
2. **Agree scope.** Use `clarify-scope` to resolve material decisions the sources cannot settle. Agree outcome, exclusions, constraints, observable acceptance and any accepted limitations before specification work.
3. **Specify and review.** Use `write-spec`. Delegate a PLAN assessment to a fresh **`plan-reviewer`** session; no self-review or substitute role. Supply the spec/index, scope/revision, relevant sources/results and applicable guidance paths or contents. The child must establish its own required context; parent-only loads and paths alone are insufficient. Await the result, resolve material findings and resume that reviewer for corrections while its basis remains valid. Scope/AC changes require user agreement. Present the corrected spec for approval and stop.

Missing reviewer, essential context or capabilities leave the affected stage incomplete. Separate optional suggestions from required corrections; reuse valid assessments without reopening settled work. Planning may write task records, not implementation, commits, pushes or external resources.
