# Hands-on Engineering Harness

Concise engineering workflows for Codex and Claude Code, packaged with stock APM.

Eleven skills cover routing, planning and delivery: `route`, `clarify-scope`, `write-spec`, `plan-slices`, `plan-feature`, `deliver-task`, `research`, `create-image`, `deliver-code`, `implement-slice` and `review-code`. Independent `plan-reviewer` and `code-reviewer` roles assess plans and changes. Planning produces an approved local plan; publication and remote delivery actions are optional.

After installation, a local project directory and native client tools are enough. No ticket system, VCS repository/client, hosting account or MCP server is required. This project's GitHub repository is its distribution source. Consumers may choose tools such as Jira/Linear or GitLab/GitHub; examples are not service-specific runtime certifications.

## Install

Use stock APM 0.35.0 and a client supporting project skills/custom agents. Install from `main` by default. See the tested support below.

```sh
# Codex
apm install ARudawski/hands-on-engineering-harness#main --target codex
apm compile --target codex

# Claude Code
apm install ARudawski/hands-on-engineering-harness#main --target claude
```

For an intentionally fixed revision, optionally replace `#main` with `#<full-commit-SHA>`. APM records the resolved commit in `apm.lock.yaml`, including when installing from a branch.

### ChatGPT plugin candidate

Build a private skills-only plugin from the same `.apm` sources with Python 3.11
and PyYAML (included with the test setup):

```sh
python scripts/build_plugin.py --output .tmp/hands-on-engineering-harness.zip
```

The archive contains ten exposed skills. Each includes its own generated copy of
the complete supporting workflow tree, shared guidance and both reviewer
contracts, so it can work without sibling skill bundles. Canonical `.apm` files
remain unchanged. Builds from identical inputs produce identical ZIP bytes;
`source-hashes.json` records canonical input hashes. Output inside this repository
must be under `.tmp/`; output elsewhere is also allowed. Generated files stay out
of commits.

To save the candidate to your account, ask Plugin Creator to create a private
plugin from that archive. Check the saved release for all ten skills and their
support files; archive validation alone does not establish ingestion. On mobile,
open the sidebar, select **Plugins**, find **Hands-on Engineering Harness**, and
install it if prompted. In a fresh Work conversation, select the plugin with `@`
and ask `Use @route: what's next?` or `Use @deliver-task to ...`.

Engineering execution needs a project filesystem and independent reviewer
sessions. The adapter loads the exact named reviewer contracts into fresh
independent sessions; it does not register Codex/Claude native agent definitions.
Unavailable filesystem, tools, reviewer context or delegation leaves the affected
work pending. Installing the plugin does not transfer your computer's projects,
credentials or connections. Advice and clarification can use available context.

This is a plugin candidate, not a certification of mobile/installed behavior.
Test routing, direct helpers, approval gates and reviewer context in the actual
target runtime before relying on engineering delivery. Account installation and
runtime observations must be reported separately from local package checks.
There is no automatic GitHub sync: rebuild after source changes and update the
existing private plugin, preserving its identity. Do not create a second plugin
to refresh an existing installation.

APM installs skills to `.agents/skills/` (Codex) or `.claude/skills/` (Claude), with native reviewer definitions and guidance. With version control, ignore `.tmp/`. Existing project/module guidance remains authoritative.

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

Ask `$route Which skill can review my current diff?` in Codex or `/route Which skill can review my current diff?` in Claude Code. A plain “what's next?” also uses the current task's progress and approvals to recommend one next step, with a reason and a concrete example. Routing ends with advice. For a reviewed specification awaiting approval, the next step is the scoped approval reply; for an approved software plan ready for delivery, it can be `$deliver-code .tmp/csv-preview/spec.md` (or `/deliver-code` in Claude Code).

In Codex, invoke `$plan-feature Add an export preview`; in Claude Code, `/plan-feature Add an export preview`. It researches, agrees scope, reviews a specification, reviews an actionable local plan, then hands it off. The first four stages pause for human approval. An existing task description or local specification is sufficient.

Use `$deliver-task <local task or issue>` in Codex, or `/deliver-task <local task or issue>` in Claude Code. It routes by the requested result. General work uses one default pre-execution checkpoint for all or selected slices, then executes, verifies and hands off. Reading code or using a temporary analysis script is general work; delivering a maintained script or software change uses `deliver-code`.

Use `$research Compare these options using the supplied sources` in Codex, or `/research` with the same request in Claude Code, to select research explicitly. `deliver-task` also selects it for a research answer/report or a research slice. The type guides question framing, source assessment, investigation and cited synthesis with clear uncertainties; `deliver-task` owns generic planning, authorization, progress and handoff. An active research slice reuses its parent's context and exact grant, then returns its findings without starting another workflow. Depth and output follow the request, from a short cited answer to a report. Routine evidence gathering within another workflow stays within that workflow.

Use `$create-image Create a workshop poster` in Codex, or `/create-image` with the same request in Claude Code. `deliver-task` also selects the type for visual deliverables or image slices. It covers expressive images and information graphics through available generation, editing or deterministic rendering tools. For an unresolved direction, explore up to four distinct rough candidates, let the user select or combine, then refine that direction. Precise edits and already selected directions skip exploration; only the user reopens it. Chart alternatives preserve data meaning. The type guides inspection, preservation and delivery while reusing the parent's authorization and record. It supplies no generator, provider account or model configuration; missing capabilities remain explicit gaps.

Invoke `$deliver-code <software task>` (or `/deliver-code` in Claude Code) directly for the same engineering path: understand, specify, slice, prepare, implement/review each slice, verify the combined change, check applicable CI and hand off. Every engineering stage and reviewed slice pauses for approval, including N/A stages. `implement-slice` handles authorized scope; `review-code` dispatches independent assessment without fixes. Helpers do not start delivery stages. Existing engineering `deliver-task` records retain their original stage meanings when resumed.

For example, `$deliver-task Reconcile these inventories and produce an exceptions report` can plan two outputs and request one grant for both. For a mixed importer-fix/report task, approving only the fix leaves the report pending; a grant naming both authorizes both portions while preserving the engineering gates. An unrequested bug found during analysis needs scope agreement before a software change.

For example, plan a bounded CSV preview with `plan-feature`, approve its local specification and plan, then pass `.tmp/csv-preview/spec.md` to `deliver-task` in the same project. Delivery retains the approved scope, IDs and decisions; publication remains optional.

All three entry points load the same planning reference on demand and reuse valid completed work, reviews and scoped approvals. Their stage order and required approval/review boundaries remain visible in each entry point; a changed input reopens the affected work. A plan-only request stops with its record.

After substantial work, the harness closes with a brief, plain-language account of the result and the next action or decision. For example, "The export specification has passed review. If you approve it, I’ll prepare and review the implementation plan." The active workflow determines the next step, including any required approval. Completed work ends with a completion message; routine clarification can simply ask its question.

Local delivery uses before/after content and path inventories when VCS is absent, including added/deleted paths. Select VCS, push, Draft review requests and hosted CI explicitly when needed. Missing selected capabilities remain pending; unselected actions are N/A. Reading an issue grants no writes. Any review request remains Draft; merge/deployment/release require separate authority.

For headless Codex CLI execution outside a repository, use its `--skip-git-repo-check` option on `codex exec`, including resumes. Keep your existing sandbox and approval policy.

Use `clarify-scope` for unresolved decisions, `write-spec` for agreed scope and `plan-slices` for small verifiable outcomes. Helpers retain their own scope; interdependent slicing requires PLAN review. Reuse `.tmp/<task>/` in the project root: navigation in `index.md`, scope/plan/IDs/approvals/evidence in `spec.md` or a linked Markdown artifact. Local planning needs no remote IDs, UUID or publication ledger.

Request publication explicitly when needed. Its exact payloads/destination receive review and separate scoped authority, within or after plan approval. Selected publication uses `tickets.md` and `publication.md` for payloads, returned identities and readback. Missing tools leave that action pending; the harness preserves usable local work and never silently drops an outstanding request. Connected tools alone do not authorize writes.

## Verification and support

| Surface | Tested scope |
| --- | --- |
| APM 0.35.0 | Both-target native skills/references, reviewers and instructions; fresh/repeat/update installs, collisions and unrelated-settings preservation. |
| Codex CLI 0.166.0-alpha.5.1, Windows | Supervised local planning, delivery and helpers; approval gates, independent review, comparison, interruption/recovery and local handoff. |
| Codex CLI 0.169.0, Windows | Supervised direct/routed research with plan approval and same-session resume; authorized research-slice reuse, evidence assessment and bounded outputs. |
| Claude Code | Native package/format checks; model execution and runtime compatibility remain assumed. |
| Package CI | Ubuntu 24.04, Python 3.11 and stock APM 0.35.0; installation/ownership, local tool-fixture and model-free smoke-driver guards, without model credentials. |

These are tested baselines, not a minimum-version or broader compatibility guarantee. No cloud, desktop-specific, plugin or live-service certification is claimed. Models and connections remain consumer-owned.

The shared-planning, general-delivery, routing and end-of-turn revisions have package checks; full native coverage of those revisions remains incomplete. The research checks below cover the described research paths only. The remaining native observations concern earlier workflow revisions.

The `create-image` type has both-target installation/reference and new-skill upgrade checks. On Linux with Python 3.11.18 and APM 0.35.0, the package suite completed 228 tests: 192 passed and 36 Windows-specific checks skipped. Supervised ChatGPT agent sessions reading APM-installed guidance exercised fresh direct/routed planning pauses and their authorized continuations through candidate selection and delivery, focused SVG refinement, explicit reopening, exact chart/diagram checks, protected edits and matching assets. Missing references and conflicting preservation requirements produced explicit blockers. These are scoped instruction and SVG observations. Native Codex CLI 0.167.0-alpha.4 could not initialize its app-server client because of a read-only-filesystem error; Claude execution, raster generation and installed ChatGPT plugin integration remain unverified.

The research type has both-target installation/reference checks and a supervised baseline-to-candidate upgrade check. The local package suite completed successfully: 227 tests, two existing skips. After clarifying fresh-task authorization in deliver-task, all three native Codex CLI 0.169.0 research checks passed. Direct and routed requests prepared a plan, paused, then resumed the same session after a plain approval and completed without another gate. An authorized research slice reused its grant and left unapproved work pending. Answers respected source/output constraints, cited inspected evidence, distinguished versions and shared provenance, and reported unavailable evidence and uncertainty. These are supervised existing-profile observations over a fixed source packet; Claude runtime behavior and broader research quality were not tested.

Local Codex checks ran outside Git with Git unavailable and service tools disabled. They verified all planning/delivery approval pauses, fresh/correction reviewers, actual context/comparison reads, missing prerequisites and preservation of unrelated files. An in-place both-target update continued the original approved CSV plan through delivery: 11 contract tests and six integration checks passed. A separate two-increment example passed 17 behavior tests; helper checks covered scoped red/green implementation and findings without fixes. Ordinary task records stayed Markdown.

Controlled provider fixtures verified actual selected schemas, reviewed/scoped publication, parent/dependency ordering, returned IDs, interruption/readback and duplicate avoidance. Unresolved/rejected/stale/foreign/ambiguous requests stopped writes; mismatched readback remained incomplete. Missing selected capabilities stayed pending. Selected delivery used real Git transport to a local bare repository and a synthetic Draft/CI host; missing/stale/running/failed/unavailable required CI could not complete validation. Only matching source/base evidence passed bounded follow-up. Fixture results do not certify a live ticket or hosting service.

Claude reviewer metadata allows `Read`, `Glob` and `Grep`. APM drops that allowlist for Codex and warns; Codex reviewers inherit parent permissions. Their inspection-only behavior is an instruction contract, not an isolated read-only sandbox. Static installed output does not prove runtime routing, context delivery or permissions.

Run package checks with Python 3.11 and stock APM 0.35.0. Installing APM in the test interpreter enables every check:

```sh
python -m pip install apm-cli==0.35.0
python -m unittest discover -s tests -v
```

APM must be on PATH, or set `APM_BIN` to a separate executable, also checked for version 0.35.0. For pipx, uv tool or standalone APM, the test interpreter needs `PyYAML` (`python -m pip install PyYAML`). Only the internal state-path probe is skipped with guidance when that interpreter lacks `apm-cli==0.35.0`; executable version checks and installation checks still run. The checks isolate APM's home, configuration, cache and temporary state. Ordinary package discovery does not invoke models.

### Optional native smoke checks

With stock APM and an authenticated Codex CLI supporting native custom agents, prepare a disposable fixture, then explicitly run one parent turn:

```sh
python tests/smoke/check_driver.py
python tests/smoke/run.py planning --output-dir .tmp/smoke/planning --prepare-only
python tests/smoke/run.py planning --output-dir .tmp/smoke/planning --resume
```

Set `APM_BIN` if needed. Preparation needs Git available for stock APM's GitPython startup. Fixtures have no Git repository and limit Git discovery above the consumer directory. The driver passes `--skip-git-repo-check` on first and resumed Codex turns. `resume-correction`, `missing-reviewer` and `missing-context` are targeted boundary cases with deliberate behavior instructions. `planning`, `clarify-scope` and `write-spec` use ordinary skill requests containing product facts and a project directory, with no preapproved records, reviewer or gate reminders. Existing consumer authentication/model settings are retained; runs request workspace-write and use the normal package installation. `--prepare-only` never calls a model.

`CODEX_BIN` optionally overrides the CLI executable found on PATH. Before each model turn, the driver records the executable/version and checks Windows sandbox file access without calling a model. A failed preflight preserves the prepared fixture and turn allowance for a retry after repair. The Windows launch-context repair was checked with both bundled and standalone executables; a separate installation is not required for that fix. See [development runtime setup](CONTRIBUTING.md#checks) for handling and diagnostics.

Inspect each turn before supplying its next input. After assessment, use `--resume --reply-file PATH`; the driver targets the recorded parent ID. A successful process stays `pending-assessment`, rather than declaring a behavioral pass. Cases allow at most eight parent turns of 1,200 seconds, followed by bounded process-tree cleanup on timeout/interruption. File-backed standard streams avoid waiting for inherited pipes. Failed/incomplete attempts cannot automatically continue or overwrite evidence. Retain failed results and allow at most one justified repeat per case.

| Case | External assessment and next input |
| --- | --- |
| `planning` | Approve research, scope, reviewed specification and reviewed local plan separately with normal `Approved.` replies. Check both fresh native reviewers/context, all four stage stops, final handoff and preservation without implementation/publication. |
| `clarify-scope` | Answer default five data rows and preservation of unused iterator rows; reject booleans/non-integer limits. Check pending choices stay unapproved until answered, then agreed scope without a reviewer/full workflow or implementation. Local scope records are permitted by the current helper. |
| `write-spec` | Agreed facts are supplied in the request. Check spec/ACs/planned checks, no invented review/final approval and no reviewer/full workflow. |
| `resume-correction` | Check original IDs/approvals/evidence and legacy content, material findings and correction verification by the same child. The targeted request stops at specification approval; it does not test the remaining plan stage. |
| `missing-reviewer`, `missing-context` | Check an explicitly incomplete review, without self-review, substitution, context repair or invented approval. |

These expectations stay outside ordinary consumer prompts. Needing to teach a workflow rule makes that ordinary case failed/incomplete; product-fact answers are allowed. Local ignored output records package/driver/selected-fixture hashes, pristine and intentionally perturbed installations, strict non-task inventories, CLI JSON events, the recorded session ID and final response. The smoke driver does not scan host session history or certify each reviewer's context/settings. Inspect reviewer context separately when testing delegation. A completed CLI process still requires external behavioral assessment. These opt-in checks stay separate from credential-free packaging CI; compatibility and performance claims require their own evidence.

Inventories retain every non-task file hash. Shared APM/native helper hashes are frozen alongside the driver; changing either helper rejects continuation. Newly generated `__pycache__/*.pyc` files are reported separately and permit continuation; existing files, source changes and other additions/deletions remain protected. A preservation failure records the changed paths. Non-JSON stdout diagnostics are counted; malformed JSON/events keep a turn incomplete while retaining later valid events.

The six-case observations below used the original driver (SHA256 `204dab1d611326cea2edfbf7b13e2b4d68d246bbd1cde457285e02da33dd220a`) with Git fixtures. The subsequent feedback fixes have focused model-free regressions, including real process-tree termination, plus a fresh no-Git helper launch/resume. Those observations predate the simplified driver and are not new executions of it. The optional model driver currently targets Codex. A [separate review report](https://github.com/ARudawski/hands-on-engineering-harness/pull/5#issuecomment-6589123411) describes manual Claude Code 2.1.309 runs and a delivery-stage approval deviation; its raw evidence has not been inspected here.

On 2026-11-02, all six cases were assessed on Windows with Codex CLI 0.166.0-alpha.5.1 and inherited `gpt-6.1-sol`/high settings, workspace-write and no network. Package-input digest: `370857eb0c6b668ab6269e936a3a55ffeac610d8671846e3723a214cf2848a14` (SHA256 of the manifest's sorted compact JSON package-hash map). Ordinary planning completed in five parent turns with four plain approvals and two fresh native reviewers whose own context reads were inspected. Helpers stayed within scope; targeted correction reused its reviewer, and missing prerequisites left review incomplete. Strict inventories preserved all 43 non-task files per ordinary/correction case and 42 per missing-prerequisite case. Eight package tests and five driver guards passed with Python 3.11.9/APM 0.35.0. Native fixture Python probes were unavailable, so preview runtime checks remain unexecuted. Host guidance/memory was readable: these are supervised existing-profile observations, not a clean-room comparison or performance benchmark.

Initial isolated observations on 2026-11-06 used full baseline `900f496` and
candidate `99c823a` installs for both targets, Docker Linux amd64 Engine 29.9.2,
Codex 0.166.0-alpha.6 and `gpt-6-astra`/xhigh. Candidate probes observed a native
question, exact-session resume, approved marker execution, a delivery-stage pause
and both installed reviewer roles with their own context/actions. The native
interrupt left a heartbeat descendant alive; the external watchdog stopped the
owned worker. The corrected cleanup stopped an actual native heartbeat command
and its descendant in 1.03 seconds with zero model requests, alongside model-free
regression checks. A fresh complete paired native sequence remains **incomplete** after the provider returned
`usageLimitExceeded`. These observations do not establish Claude execution,
calibration, performance or complete evaluator acceptance.

See [contribution guidance](CONTRIBUTING.md) for changes and validation.

Isolated evaluator feasibility tooling is documented in
[tests/evaluation](tests/evaluation/README.md). It uses full pinned repository
installations and explicit worker/native containment gates, separately from the
reduced smoke fixtures above. The signed-in candidate path keeps the full install
private and exposes its deployed assets in a separate workspace. A prior native
trial had readable answer hints and does not establish clean quality measurement.
Docker/model execution is opt-in; ordinary package
and driver CI remains credential-free.

## License

New content uses the [MIT License](LICENSE); see [third-party notices](THIRD-PARTY-NOTICES.md).
