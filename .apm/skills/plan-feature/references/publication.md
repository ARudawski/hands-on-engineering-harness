# Optional work-item publication

Load this reference only for selected publication. Use the chosen tools and their actual schemas. Discover destination, required fields, supported relationships, canonical baseline and overlapping work. Do not infer a provider, tool name, team/project hierarchy or optional metadata. A capability needed for the requested representation must be available before promising writes. Missing access blocks that action, not independent local work; report it as pending without silently changing the request. Provider examples such as Linear/Jira do not imply runtime certification.

## Exact batch

Keep exact proposed payloads in `tickets.md` or a linked batch: outcome/AC coverage, verification, supported dependencies, destination and every intended create/update/link/document write. Reference existing work by explicit remote ID; include its role and approved changes. Creating a destination or changing a canonical document requires explicit inclusion. Do not silently omit an unsupported relationship; agree its representation before approval.

Generate one batch UUID before review. Include `Planning batch: <uuid>; draft: <id>` in every new resource's supported description/body, as part of the reviewed payload. Preserve that identity across revisions and resume; draft IDs alone and matching titles do not establish ownership. No custom field is required.

Freeze the reviewed payload or record its fingerprint. Capture approval of that exact revision, destination and publication action. Only specified substitutions of returned IDs/URLs are automatic. Material scope, payload, destination or external-state changes require affected review and renewed approval.

Respect the consumer's chosen canonical baseline; approved local records are the default. Identify its revision and any working-copy/task delta. If publication creates/updates it, include the exact content and intended revision in the batch and reconcile local records after readback.

## Publish and recover

Before initial writes and on resume, re-read destination/canonical revision, capabilities, related resources and overlapping work. Use a compact `publication.md` ledger with draft-to-remote ID/URL, successful operations, pending/uncertain work and readback. Preserve approvals and evidence.

- Create approved parents before children. After every successful write, record its returned identity and completed operation **before another dependent call**. Then use real IDs for parent/dependency/link reconciliation.
- After an uncertain result, record uncertainty and inspect state before retrying. Recovery needs one exact marker, destination and approved-content match. Ambiguous matches or unapproved foreign lookalikes stop dependent writes: neither adopt them nor create duplicates. A missing match after an inconclusive lookup is not proof that the write failed.
- Resume only operations shown to be missing and still approved. Retry a transient read once; unresolved identity/outcome stops recovery. Do not blindly retry mutations or automatically delete/roll back shared resources.
- Read back final content, associations, dependencies, links and canonical revision. Compare intended fields semantically, allowing native Markdown/ID formatting. Missing or mismatched readback means incomplete publication, not success.

Report created/reused resources, URLs, ID mapping, verified results, remaining operations and blockers. External defaults are observed facts, not newly approved payload choices. Keep credentials out of all records.
