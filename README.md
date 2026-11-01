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

APM installs skills to `.agents/skills/` (Codex) or `.claude/skills/` (Claude), with native reviewer definitions and guidance. Review generated changes, especially an existing root `AGENTS.md` before/after compilation. Add `.tmp/` to the consumer's ignore file. Existing project/module guidance remains authoritative.

The package supplies no installer hooks, provider/model pins or MCP configuration. Use your existing models, credentials and configured tools.

## Use

In Codex, invoke `$plan-feature Add an export preview`; in Claude Code, `/plan-feature Add an export preview`. The workflow researches, agrees scope, writes a specification and dispatches independent review, pausing for approval after each stage.

Use `clarify-scope` for unresolved decisions and `write-spec` for already agreed scope. Task records live in the active worktree's `.tmp/<task>/`: `index.md` is navigation; `spec.md` holds the specification, decisions and evidence.

## Verification and limits

- Packaging checks use stock APM 0.35.0 and Python 3.11; run `python -m unittest discover -s tests -v` with APM on PATH (or set `APM_BIN`). CI runs these checks without model credentials.
- Codex CLI 0.166.0-alpha.5.1 on Windows passed a synthetic planning smoke covering stage approval pauses, native reviewer context delivery and the stop after specification approval.
- Claude Code compatibility is assumed from native format/package checks; no Claude model execution is claimed.
- Claude's reviewer metadata allows `Read`, `Glob` and `Grep`. Stock APM drops that allowlist for Codex and reports a warning. Codex inherits parent permissions; its review-only behavior is an instruction contract, not an isolated sandbox. This configuration does not provide enforced tool isolation in Codex.

Static installation checks do not prove routing, context delivery or runtime permission behavior. No cloud or desktop-specific compatibility is claimed.

## License

New content uses the [MIT License](LICENSE); see [third-party notices](THIRD-PARTY-NOTICES.md).
