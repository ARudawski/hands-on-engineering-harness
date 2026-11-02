---
name: review-code
description: Dispatch an independent code-reviewer assessment of an identified change, returning findings and gaps without fixes.
---

# Review code

Use a fresh **`code-reviewer`** session for a new assessment; no self-review or substitute role. Resume that same reviewer for corrections while its basis remains valid. Supply scope/revision, task spec/index and relevant durable requirements, applicable guidance, comparison, check results/gaps and unrelated-edit boundaries. The child must actually establish its required context; parent-only loads and unread paths are insufficient.

Identify the comparison: resolve available VCS references and include staged, unstaged and relevant untracked changes unless scope says otherwise. Without VCS, supply reproducible before/after content and a path inventory including added/deleted paths. A summary alone is insufficient; missing essential comparison, context or named reviewer leaves the assessment incomplete.

Await the assessment and return its scoped findings/gaps, separating required corrections from optional suggestions. The parent maintains records and supplies remote/check evidence. Do not start fixes, implementation, extra workflow stages or external actions.
