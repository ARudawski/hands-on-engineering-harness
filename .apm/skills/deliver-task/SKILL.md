---
name: deliver-task
description: Plan and deliver general or mixed computer tasks, routing maintained software changes through deliver-code.
---

# Deliver a task

Load applicable guidance, required skills and [shared planning][planning]. Use one project-root `.tmp/<task>/spec.md` and navigation index for the requested deliverables. Preserve IDs, decisions, exact approvals, evidence and next action on resume. A local task or existing plan is sufficient; no repository or external service is required.

[planning]: ../clarify-scope/references/planning.md
[engineering]: ../deliver-code/SKILL.md

## Select the workflow

Route by the deliverable the user expects to keep, honoring explicit workflow selection and project requirements:

- **General work:** documents, reports, reconciliation, research and other computer tasks. Reading code or using a disposable analysis script does not make the deliverable software.
- **Software:** maintained scripts, application changes, automated tests and build/deployment configuration. Continue through [deliver-code][engineering] with the current record and exact next authorized action. Its eight-stage workflow, reviews and approval gates apply unchanged; do not run a generic checkpoint first.
- **Mixed work:** keep one plan/record and apply `deliver-code` to the software portion. Track each portion's workflow, checks and authority explicitly; verify the combined result at handoff.

For existing records, retain the recorded workflow before interpreting a stage number. Legacy engineering `deliver-task` records resume through `deliver-code` with their original stage meanings. Reuse valid completed planning and approvals by meaning and scope. Clarify a genuinely ambiguous route or saved stage before dependent work.

## General delivery

There is one default pre-execution checkpoint. Specific user/project requirements may add approvals or independent review. Shared planning and helper calls do not add routine checkpoints. There is no standing code-review or CI step for general work.

1. **Prepare the plan.** Apply shared planning's Evidence, Scope, Specification and Work plan portions to the task's complexity. Record as many small verifiable slices as useful, each with a stable ID, scope and observable completion check. Resolve material questions before dependent work. A plan-only request stops with the usable record and next available action.
2. **Authorize execution.** Present the plan and name the exact actions/slices approval will authorize, then pause. The user may authorize all or a subset; record the actual grant for each slice. Reuse an existing valid execution grant without asking again. Planning approval or route selection alone grants no execution or publication authority.
3. **Execute authorized slices.** Perform only granted work, check each result and record its evidence/gaps before continuing. Unapproved slices remain pending. On interruption, resume from the recorded results and grant without repeating completed work or inventing approval. Diagnose failures and bound retries; changed scope or required authority needs agreement before dependent action.
4. **Verify and hand off.** Check the overall result and interactions against the agreed acceptance criteria. Deliver outputs in their requested locations, retain concise evidence and pending work in the record, and state what happens next or that the work is complete. No routine second approval is required after authorized general work.

## Mixed tasks and scope changes

An existing engineering checkpoint may request authority for both software and general slices if it names both actions and their scope. A grant covering both satisfies the general pre-execution checkpoint while preserving all later engineering gates. Approval of an importer fix alone leaves its report pending; a grant covering the fix and report authorizes both within their stated scope. Keep the engineering portion's stage separate from general progress so stage numbers cannot change meaning.

If analysis discovers an unrequested software fix, record it and seek scope agreement before changing software. Do not silently expand an analysis task into engineering delivery.

Select external writes only from explicit task/project requirements and scoped authority. Use actual capabilities; unavailable selected actions stay pending, while unselected actions are N/A. Reading an issue or having connected tools grants no write authority. Preserve unrelated files/settings and keep credentials out of records.
