# Hands-on Engineering Harness

Concise engineering workflows for Codex and Claude Code, packaged with stock APM.

**Unreleased planning foundation.** Available: `clarify-scope`, `write-spec`, `plan-feature` and the independent `plan-reviewer`. Planning ends at reviewed-spec approval; ticket drafting, publication and delivery are outside this version.

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

In Codex, invoke `$plan-feature Add an export preview`; in Claude Code, `/plan-feature Add an export preview`. The workflow researches, agrees scope, writes a specification and dispatches independent review, pausing for approval after each stage.

Use `clarify-scope` for unresolved decisions and `write-spec` for already agreed scope. Task records live in the active worktree's `.tmp/<task>/`: `index.md` is navigation; `spec.md` holds the specification, decisions and evidence.

## Verification and limits

- Packaging checks use stock APM 0.35.0 and Python 3.11; run `python -m unittest discover -s tests -v` with APM on PATH (or set `APM_BIN`). They cover fresh/repeat/update installs, collisions and guidance preservation. CI needs no model credentials.
- Codex CLI 0.166.0-alpha.5.1 on Windows passed synthetic planning, resume/correction and missing-context/reviewer scenarios: stage pauses, native reviewer context delivery and the stop after specification approval.
- Claude Code compatibility is assumed from native format/package checks; no Claude model execution is claimed.
- Claude's reviewer metadata allows `Read`, `Glob` and `Grep`. Stock APM drops that allowlist for Codex and reports a warning. Codex inherits parent permissions; its review-only behavior is an instruction contract, not an isolated sandbox. This configuration does not provide enforced tool isolation in Codex.

Static installation checks do not prove routing, context delivery or runtime permission behavior. No cloud or desktop-specific compatibility is claimed.

## License

New content uses the [MIT License](LICENSE); see [third-party notices](THIRD-PARTY-NOTICES.md).
