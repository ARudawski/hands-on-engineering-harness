---
name: route
description: Recommend a harness skill or the next actionable step when the user asks where to start, which skill to use, or what's next.
---

# Find the next step

Use applicable guidance, the current conversation and the active task record when available. For skill selection, use the shared routing table and read the relevant installed skill's instructions before recommending its user-facing entry point. Reuse unchanged context. Keep routing read-only and finish with advice; leave task records, approvals and external state untouched, and leave execution and reviewer dispatch to the selected workflow.

For ongoing work, identify the next unresolved decision, required review, approval or action within that workflow. An approved plan, a completed check and an approved action have different meanings; use the recorded scope of each. When context conflicts, check the relevant evidence or ask the user before treating a step as complete.

Give one next step, a short reason and a concrete example the user can copy or carry out. Use `$skill-name` for Codex and `/skill-name` for Claude Code when a command is appropriate. An approval reply or missing input can be the next step; explain exactly what it would authorize or unblock. For example, a reviewed export spec awaiting approval calls for a reply such as “Approve the export spec and prepare its implementation plan.”

If a missing fact changes the choice, ask one focused question. If a prerequisite is unavailable, name it and the action needed to unblock progress. If no available skill fits the request, say so. When the requested work and its required approvals are complete, report completion and stop.
