# Shared planning

Read the portions selected by the calling workflow. This reference supplies planning work, not another workflow or approval gate. The caller keeps its stage order, required assessments, pauses and authority to act. Helpers retain their standalone scope; the caller can satisfy a helper's review requirement once for the exact artifact.

## Evidence

Read the request, relevant comments/specifications, existing task records and affected code, tests or other contracts. Identify reusable capabilities and overlapping work. Check consequential assumptions with the smallest representative check before dependent work. Distinguish observed facts, assumptions and inaccessible evidence.

## Scope

Use [clarify-scope](../SKILL.md) for material decisions the evidence cannot settle. Agree the outcome, exclusions, constraints, observable acceptance and accepted limitations before dependent specification work. Resolve only open questions; do not reopen settled decisions without conflicting evidence.

## Specification

Use [write-spec][specification] to record agreed scope, numbered acceptance criteria and a planned check for each. Preserve IDs and accepted limitations; link approved durable baselines and influential sources. Agree material scope or acceptance changes rather than treating them as an editorial update.

## Work plan

Order the smallest useful verifiable outcomes. Give each a stable ID, scope, completion check, acceptance coverage and real dependencies; one slice can suffice. Feature planning and engineering delivery use [plan-slices][slices], returning its plan and review need to the caller. General delivery can record its slices directly; reviews apply only when its caller or project requires them. Do not add duplicate assessments or checkpoints when the caller already covers the exact plan and interactions.

[specification]: ../../write-spec/SKILL.md
[slices]: ../../plan-slices/SKILL.md

## Records, handoff and resume

Use the active project's `.tmp/<task>/`: the worktree root when applicable, otherwise the active folder without requiring a repository. Keep `index.md` to navigation. Keep scope, numbered criteria/checks, approach/plan, IDs, decisions, approvals and their scope, evidence/gaps and next action in `spec.md`; link larger details. Deliverables stay in their requested project locations; task records stay out of published source.

Reuse valid evidence, completed work, assessments and approvals for corresponding planning work by meaning and scope, including when moving between workflows. Do not repeat satisfied work or its approval. Changed inputs reopen affected decisions, checks, reviews and approvals while retaining unaffected evidence. Clarify an ambiguous saved stage before advancing; do not reinterpret its number under another workflow.

Planning approval grants no implementation, commit, push or publication authority. Record the next action and any authority still needed. A plan-only request ends with the usable record and handoff; it does not start execution.
