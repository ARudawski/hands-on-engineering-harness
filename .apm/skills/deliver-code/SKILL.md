---
name: deliver-code
description: Deliver maintained software changes through approved slices, independent reviews and optional VCS, CI and remote handoff.
---

# Deliver a software change

Load applicable guidance, required skills and [shared planning][planning]. Use its records and reuse rules for the portions selected below. A local task/plan is enough. Reconcile actual changes, comparisons, results/gaps and next authorized action on resume.

[planning]: ../clarify-scope/references/planning.md

Direct invocation and software requests forwarded by `deliver-task` use this same workflow and task record. Resume legacy engineering `deliver-task` records with their original eight-stage meanings, valid approvals and next authorized action; clarify an ambiguous stage before advancing. A rename or handoff grants no new authority.

After **every numbered stage and each reviewed slice in stage 5**, present results and next action, then end the turn for human approval, including N/A stages. Earlier approval does not approve a later result. Select VCS operations, push, Draft review requests and hosted CI only from explicit task/project requirements; connections or remote issue input grant no writes. Record unselected actions as N/A with a reason; unavailable selected actions remain pending, never silently replaced by local success.

1. **Understand.** Apply shared planning's Evidence and Scope portions; present understanding, acceptance and gaps for approval.
2. **Specify.** Apply its Specification portion; present the specification for approval.
3. **Slice.** Apply its Work plan portion. Interdependent slices/unclear interfaces need independent `plan-reviewer` assessment before approval; correct findings in that session. Present the slice plan for approval.
4. **Prepare.** Preserve unrelated edits and establish the comparison before implementation: resolve available VCS references and pending changes, or capture before-content/path inventory and retain resulting after-state evidence, including added/deleted paths. Prepare local work; branch/base, push and Draft review requests apply only when selected. Follow project-specific timing; keep any review request Draft.
5. **Implement each slice.** Use `implement-slice` → relevant checks → `review-code` → required corrections → affected checks and same-reviewer verification → human approval. Include staged, unstaged and relevant untracked changes or their local comparison equivalents. Slice approval authorizes only its applicable commit and stated next action; commit/push only when selected and authorized. Optional suggestions need no correction loop.
6. **Verify the whole change.** Reconcile AC evidence/gaps and verify integration/cross-slice effects. Establish independent CODE-review coverage using `review-code`; reuse valid assessments and inspect uncovered interactions instead of repeating unchanged work. Required corrections return through the slice loop.
7. **Validate applicable CI.** For required CI, identify current source/base and the tested revision (SHA when available). Missing/stale/running results remain gaps; poll with a bound and record the run/status/next action if unfinished. Inspect failures, report supported cause/proposed correction and pause for approval before the slice loop. Retry only after relevant change or a justified bounded transient retry. If CI is unselected, record N/A and retain local checks; still pause.
8. **Hand off.** Reconcile source, records, affected durable documentation, results and limitations. Perform only authorized selected remote updates; report pending actions without claiming full completion. Route any further source edits through the slice loop. Present final results for approval; keep any review request Draft. No automatic merge, deployment or release.

Dispatch new PLAN/CODE assessments to fresh named reviewer sessions; resume each for corrections while its basis remains valid. Supply actual required context and a reproducible comparison, not just paths or a change summary. Missing essential guidance, reviewer, comparison or checks leaves the affected review/stage incomplete. Planning and reused evidence grant no new implementation or external authority.
