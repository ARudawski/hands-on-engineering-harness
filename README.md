# Hands-on Engineering Harness

Concise engineering workflows for Codex and Claude Code, packaged with stock APM.

**Unreleased workflow package.** Seven skills cover planning and delivery: `clarify-scope`, `write-spec`, `plan-slices`, `plan-feature`, `deliver-task`, `implement-slice` and `review-code`. Independent `plan-reviewer` and `code-reviewer` roles assess plans and changes. Planning produces an approved local plan; publication and remote delivery actions are optional.

After installation, a local project directory and native client tools are enough. No ticket system, VCS repository/client, hosting account or MCP server is required. This project's GitHub repository is its distribution source. Consumers may choose tools such as Jira/Linear or GitLab/GitHub; examples are not service-specific runtime certifications.

## Install

Use APM 0.35.0 and a client supporting project skills/custom agents. Replace `REF` with a reviewed commit from the development branch; there is no release tag yet.

```sh
# Codex
apm install ARudawski/hands-on-engineering-harness#REF --target codex
apm compile --target codex

# Claude Code
apm install ARudawski/hands-on-engineering-harness#REF --target claude
```

APM installs skills to `.agents/skills/` (Codex) or `.claude/skills/` (Claude), with native reviewer definitions and guidance. Add `.tmp/` to the consumer's ignore file. Existing project/module guidance remains authoritative.

The package supplies no installer hooks, provider/model pins or MCP configuration. Use your existing models, credentials and configured tools.

## Existing projects

Resolve collisions before use: an install can succeed while skipping a reviewer. Stock APM 0.35.0 behaves as follows:

| Package path | Ownership and collisions |
| --- | --- |
| Native skill folders | Unmanaged same-path conflicts refuse installation. Modified managed skills are retained with diagnostics. |
| Native reviewer files | Unmanaged same-path files are skipped; APM-managed files are replaced on reinstall. |
| `.claude/rules/harness.md` | Replaced on install, including an existing consumer-authored file. Reserve this path. |
| Root `AGENTS.md` | Hand-authored files are protected with a warning; APM-generated files are regenerated. |

Keep local additions in separate files. Unrelated skills, agents, rules and client/MCP settings are preserved by the tested fixtures. Review diffs after installation and compilation; local edits to generated files are not generally preserved.

For an existing hand-authored `AGENTS.md`, default compilation leaves it unchanged without adding harness guidance. To retain local text and compile the harness, add this to the **consumer's** `apm.yml`:

```yaml
compilation:
  agents_md:
    mode: managed_section
```

Add `<!-- apm:start -->` and `<!-- apm:end -->` on separate lines in `AGENTS.md`, then rerun `apm compile --target codex`. APM replaces only that block; keep local instructions outside it.

## Use

In Codex, invoke `$plan-feature Add an export preview`; in Claude Code, `/plan-feature Add an export preview`. It researches, agrees scope, reviews a specification, reviews an actionable local plan, then hands it off. The first four stages pause for human approval. An existing task description or local specification is sufficient.

Use `$deliver-task <local task or issue>` in Codex, or `/deliver-task <local task or issue>` in Claude Code. It understands, specifies, slices, prepares, implements/reviews each slice, verifies the combined change, checks applicable CI and hands off. Every stage and reviewed slice pauses for approval, including N/A stages. `implement-slice` handles authorized scope; `review-code` dispatches independent assessment without fixes. Helpers do not start delivery stages.

Local delivery uses before/after content and path inventories when VCS is absent, including added/deleted paths. Select VCS, push, Draft review requests and hosted CI explicitly when needed. Missing selected capabilities remain pending; unselected actions are N/A. Reading an issue grants no writes. Any review request remains Draft; merge/deployment/release require separate authority.

For headless Codex CLI execution outside a repository, use its `--skip-git-repo-check` option on `codex exec`, including resumes. Keep your existing sandbox and approval policy.

Use `clarify-scope` for unresolved decisions, `write-spec` for agreed scope and `plan-slices` for small verifiable outcomes. Helpers retain their own scope; interdependent slicing requires PLAN review. Reuse `.tmp/<task>/` in the project root: navigation in `index.md`, scope/plan/IDs/approvals/evidence in `spec.md` or a linked Markdown artifact. Local planning needs no remote IDs, UUID or publication ledger.

Request publication explicitly when needed. Its exact payloads/destination receive review and separate scoped authority, within or after plan approval. Selected publication uses `tickets.md` and `publication.md` for payloads, returned identities and readback. Missing tools leave that action pending; the harness preserves usable local work and never silently drops an outstanding request. Connected tools alone do not authorize writes.

## Verification and limits

- Checks use stock APM 0.35.0 and Python 3.11; run `python -m unittest discover -s tests -v` with APM on PATH (or set `APM_BIN`). They cover native assets, fresh/repeat/update installs, collisions, guidance preservation and the local tool fixture. CI needs no model credentials.
- Supervised Codex CLI 0.166.0-alpha.5.1 runs on Windows verified local planning/resume outside Git with Git unavailable, no service calls, all four approval pauses and separate native specification/plan reviews. Ordinary task records stayed Markdown.
- A synthetic flat-board schema verified later publication review, a returned key/URL checkpoint and resumed readback without duplicate creation. Missing selected capability remained pending. Later publication starts a fresh reviewer; corrections reuse that publication reviewer. No live service certification is implied.
- Local fixtures verified approved payloads, parent-first publication, ID checkpoints, dependencies, readback and recovery after interruption/lost response. Unresolved scope, rejected/stale batches, missing writers and foreign/ambiguous matches stopped writes; mismatched readback remained incomplete. No live Linear publication was tested.
- Claude Code compatibility is assumed from native format/package checks; no Claude model execution is claimed.
- Supervised Codex CLI checks also verified local delivery outside Git: two dependent increments, before/after comparisons including added/deleted files, every stage/slice pause (including prepare/CI N/A), separate PLAN/CODE assessments, combined review and local handoff. The example application passed 17 behavior tests; protected notes/settings stayed unchanged.
- Standalone helper checks verified scoped implementation with two red-to-green tests and independent CODE findings without fixes or extra delivery stages. Reviewer transcripts establish actual context/comparison reads and inspection-only behavior. Delivery interruption, CODE correction sessions and selected-integration/CI cases remain pending.
- Claude's reviewer metadata allows `Read`, `Glob` and `Grep`. Stock APM drops that allowlist for Codex and reports a warning. Codex inherits parent permissions; its review-only behavior is an instruction contract, not an isolated sandbox. This configuration does not provide enforced tool isolation in Codex.

Static installation checks do not prove routing, context delivery or runtime permission behavior. No cloud or desktop-specific compatibility is claimed.

## License

New content uses the [MIT License](LICENSE); see [third-party notices](THIRD-PARTY-NOTICES.md).
