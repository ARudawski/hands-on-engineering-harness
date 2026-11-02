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

For documentation-only changes, check accuracy, references and support claims. Update the README when public behavior or tested support changes. Do not publish a tag/release or claim new client/service support from a passing package test alone.

Release approval identifies the exact tag/commit, notes, successful checks and accepted limits. Read back the tag and release after publication.
