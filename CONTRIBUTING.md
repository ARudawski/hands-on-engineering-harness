# Contributing

Keep changes small and describe the problem, resulting behavior, checks and remaining limits in the pull request. This repository uses GitHub; installed workflows remain local by default, with ticket systems, version control and hosting optional.

Edit shared skills, reviewers and guidance under `.apm/`. Keep `apm.yml` declarative; generated client files, task records, credentials and local test outputs do not belong in commits. Retain the [MIT license](LICENSE) and required [third-party notices](THIRD-PARTY-NOTICES.md).

Preserve approval gates, independent review, scoped authorization, resumable records and unrelated consumer files. Missing selected capabilities must remain pending. Avoid new runtimes, installer hooks, provider/model pins and global-setting changes.

## Checks

Use Python 3.11 with stock APM 0.35.0:

```sh
python -m pip install apm-cli==0.35.0
python -m unittest discover -s tests -v
git diff --check
```

The suite checks native assets, install/repeat/update behavior, collisions, guidance ownership and the local tool fixture. `APM_BIN` can select an existing APM executable. CI runs these package checks without model credentials.

For behavior changes, exercise the affected installed-client path and approval/review boundaries; use a failing then passing check where a suitable seam exists. Inspect actual reviewer context/actions when changing delegation. Reuse unaffected evidence and record exact client/APM versions, surfaces and gaps. Static packaging checks do not establish model execution; keep support claims within observed results and explicitly accepted assumptions.

For Codex native checks, use an authenticated CLI. The driver uses PATH by default; `CODEX_BIN` optionally selects another executable, such as a standalone installation when the bundled version has a runtime problem. On Windows, the standard standalone installer places it at `$env:LOCALAPPDATA\Programs\OpenAI\Codex\bin\codex.exe`. Keep executable selection in the calling environment; do not commit machine paths or change consumer model/authentication settings.

The smoke driver checks CLI startup and, on Windows, sandboxed file access before starting a model turn. A failed preflight records a diagnostic without consuming a turn; correct the runtime and resume the prepared fixture. Shared native launches remove the inherited `CODEX_WINDOWS_REGISTERED_CORE` desktop invocation marker only in the child environment. This prevents `registered Core launch requires an installed app` from an unrelated desktop launch context while retaining managed configuration and workspace permissions. Use `codex doctor` for remaining runtime failures; preserve failed evidence and do not disable sandboxing to get a passing check.

For documentation-only changes, check accuracy, references and support claims. Update the README when public behavior or tested support changes. Do not publish a tag/release or claim new client/service support from a passing package test alone.

Release approval identifies the exact tag/commit, notes, successful checks and accepted limits. Read back the tag and release after publication.
