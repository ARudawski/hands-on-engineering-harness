# Hands-on Engineering Harness

Concise engineering workflows for Codex and Claude Code, packaged with stock APM.

**Unreleased planning workflow.** Available: `clarify-scope`, `write-spec`, `plan-slices`, `plan-feature` and the independent `plan-reviewer`. Planning runs through approved Linear publication. Ticket implementation/delivery remains outside this version.

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
| Native `plan-reviewer` files | Unmanaged same-path files are skipped; APM-managed files are replaced on reinstall. |
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

In Codex, invoke `$plan-feature Add an export preview`; in Claude Code, `/plan-feature Add an export preview`. The workflow researches, agrees scope, reviews a specification, drafts/reviews the exact ticket batch, then publishes it. The first four stages pause for human approval; publication requires approval of the exact batch and destination.

Use `clarify-scope` for unresolved decisions, `write-spec` for agreed scope and `plan-slices` for small verifiable outcomes. Helpers retain their own scope; interdependent slicing requires PLAN review. Records live in `.tmp/<task>/`: index links, scope/approvals in `spec.md`, exact drafts in `tickets.md`, and returned IDs/operations/readback in `publication.md`. Batch/draft markers in approved payloads support recovery; ambiguous or changed state stops dependent writes.

## Verification and limits

- Checks use stock APM 0.35.0 and Python 3.11; run `python -m unittest discover -s tests -v` with APM on PATH (or set `APM_BIN`). They cover native assets, fresh/repeat/update installs, collisions, guidance preservation and the local tool fixture. CI needs no model credentials.
- Supervised Codex CLI 0.166.0-alpha.5.1 runs on Windows verified approval pauses, separate specification/batch reviewers, standalone slicing and a reviewer correction in the same session.
- Local fixtures verified approved payloads, parent-first publication, ID checkpoints, dependencies, readback and recovery after interruption/lost response. Unresolved scope, rejected/stale batches, missing writers and foreign/ambiguous matches stopped writes; mismatched readback remained incomplete. No live Linear publication was tested.
- Claude Code compatibility is assumed from native format/package checks; no Claude model execution is claimed.
- Claude's reviewer metadata allows `Read`, `Glob` and `Grep`. Stock APM drops that allowlist for Codex and reports a warning. Codex inherits parent permissions; its review-only behavior is an instruction contract, not an isolated sandbox. This configuration does not provide enforced tool isolation in Codex.

Static installation checks do not prove routing, context delivery or runtime permission behavior. No cloud or desktop-specific compatibility is claimed.

## License

New content uses the [MIT License](LICENSE); see [third-party notices](THIRD-PARTY-NOTICES.md).
