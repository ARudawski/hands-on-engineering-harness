# Isolated native feasibility checks

Opt-in developer tooling for evaluator outcome E01 / HAR-5. Ordinary package tests
exercise its model-free guards; they never launch Docker workers or models.
Complete bug workflows, private trial repositories and authoritative grading are
separate evaluator outcomes.

The currently selected deployment is Docker Desktop's Linux amd64 Engine 29.9.2,
stock APM 0.35.0 and Codex 0.166.0-alpha.6. The Dockerfile pins its Python base by
digest. Build from the **tests** context, which contains no host task records:

```sh
docker build -t harness-eval-tools -f tests/evaluation/Dockerfile tests
docker image inspect harness-eval-tools
```

Supply the returned immutable image ID in a private JSON input file. Required
fields are comparison_id, case_id, variant (baseline/candidate), full baseline and
candidate SHAs, model, effort (xhigh), image_id, fixture_revision, codex_version
(0.166.0-alpha.6), apm_version (0.35.0), and limits with turns=8,
turn_seconds=1200, trial_seconds=7200 and cancel_seconds=10. Model/auth access is
explicit: the controller environment supplies OPENAI_API_KEY to the separate
trusted relay only. Never put credentials in the input file or mount a host
Codex home into the worker.

```sh
python tests/evaluation/run.py prepare --config /private/input.json --output .tmp/evaluation/trial
python tests/evaluation/run.py preflight --output .tmp/evaluation/trial
python tests/evaluation/run.py sandbox-gate --output .tmp/evaluation/trial
python tests/evaluation/run.py report --output .tmp/evaluation/trial
```

Preparation installs the **complete pinned repository** normally for Codex and
Claude, compiles Codex guidance, verifies required assets against source blobs,
and records full materialized/deployed hashes. The implementation utility base
and evaluated source SHAs are separate identities. No model is run by preparation
or either preflight. Missing inputs, drift or a failed prerequisite block native
execution; process success alone is not behavioral acceptance.

The worker has no host bind mounts, daemon socket, capabilities or external DNS.
Its single internal network reaches a per-trial model relay. A narrow, hashed
amd64 seccomp extension to the engine-pinned default permits private user
namespaces for Codex's native bubblewrap sandbox; it retains default syscall
denial, nonroot execution and no-new-privileges. No unconfined or approval-bypass
mode is used. Unsupported engine/policy/native behavior remains a blocker.

Protected-file, prior-worker/session/cache, reachable-network and DNS controls,
native forbidden writes and child actions must all pass. Relay denial reasons and
external metering are retained; hosted tools, stored state, model drift and
unsupported operations are rejected before inference. The relay is controller
armed only, with shared request/concurrency/byte/token/time limits for direct and
child traffic. Worker-readable tooling is not the authoritative instance.

Outputs and returned resource identities remain private and outside source.
Retain failed preparation records; do not edit them into successful runs or
silently adopt a different session/configuration. Resource ownership is checked
by exact identity and labels. Never delete resources inferred only from a name
prefix. Package/driver success and both-target installation do not certify Claude
behavior, hosted GitHub workflows or complete evaluator operation.
