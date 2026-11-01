---
name: write-spec
description: Turn agreed scope into a concise implementation specification with acceptance criteria and checks.
---

# Write specification

Load applicable guidance and existing task records. Write/update `<project-root>/.tmp/<task>/spec.md`; reuse its directory. A worktree root applies when present; otherwise use the active project directory without requiring VCS tools. Resolve material uncertainty before presenting a requirement as agreed.

Include the objective, scope/non-goals, observable numbered ACs, approach/interfaces, decisions, sources and a planned check for each AC. Reuse IDs. Link applicable approved requirements and accepted durable decisions; describe the task delta rather than copy the baseline.

Keep approvals, actual results/gaps and next authorized action compact. `index.md` contains links with short descriptions only. Preserve unrelated decisions and existing evidence. If migrating an embedded index specification, retain its source snapshot and reconcile an existing spec; formatting alone creates no new approval.

Report the path and unresolved questions. Do not invent approval, create tickets, publish, implement or add slices. A parent workflow owns its next stage and approval gate.
