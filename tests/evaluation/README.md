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

The bundled public fixture revision is `native-foundation-v2`. Its immutable
scope is `contract.md`; ordinary workflow task records such as `spec.md` may be
written under the designated task root without changing that input.

```sh
python tests/evaluation/run.py prepare --config /private/input.json --output .tmp/evaluation/trial
python tests/evaluation/run.py preflight --output .tmp/evaluation/trial
python tests/evaluation/run.py sandbox-gate --output .tmp/evaluation/trial
python tests/evaluation/run.py probe --output .tmp/evaluation/trial --stop-after question
# Read session_id from manifest.json; never use latest/title lookup.
python tests/evaluation/run.py resume --output .tmp/evaluation/trial --session-id EXACT_RECORDED_ID
python tests/evaluation/run.py report --output .tmp/evaluation/trial
```

Preparation installs the **complete pinned repository** normally for Codex and
Claude, compiles Codex guidance, verifies required assets against source blobs,
and records full materialized/deployed hashes. The implementation utility base
and evaluated source SHAs are separate identities. No model is run by preparation
or either preflight. Missing inputs, drift or a failed prerequisite block native
execution; process success alone is not behavioral acceptance.

The bounded native sequence observes a real question, one exact benign native
permission approval, the first delivery workflow pause, both installed reviewer
roles and their own context/actions, then active-turn/descendant cancellation.
Cancellation uses the native interrupt and dedicated worker-process cleanup;
heartbeat readback then verifies the descendant stopped within the same ten
seconds. A native interrupted status alone does not establish descendant cleanup.
Project trust is configured only in the fresh trial home and hash-checked.
Unknown, stale, duplicate or mismatched requests block; no workflow stage is
automatically approved. These public transport tasks are not hidden grading
vectors or the later full-workflow response engine.

Each completed checkpoint preserves the exact parent/session-tree identity.
Resume requires that explicit ID and unchanged inputs, installations, trust and
effective permission state. An interrupted or failed operation is not silently
replayed. Every new preparation allocates fresh trial/attempt/resources; retain
previous evidence and document any retry/correction lineage separately.

The exact client uses stateless Responses requests with `reasoning.context` set
to `all_turns` and local tools declared inline through `additional_tools`.
The relay validates these locations too; stored-state references, hosted tools
and remote media remain forbidden. Only inline text tool results are accepted.
Native local `agent_message` envelopes accept inline text and opaque inherited
context. Evidence exports remove structured reasoning and `encrypted_content`
fields; opaque native message strings inside serialized tool arguments remain.
If admission closes during
upstream connection setup, the disposable relay exits with its reason retained;
it cannot restart to reset quotas or send later from a stranded setup thread.

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

`report` writes matching JSON/Markdown evidence summaries without claiming an
automated behavioral pass. The execution and later collector identities stay
distinct. Raw reasoning/history is extracted only temporarily; retained native
exports contain own actions/context and filter reasoning items recursively.

After retaining reports, explicitly retire only the recorded probe resources:

```sh
python tests/evaluation/run.py retire --output .tmp/evaluation/trial
```

Retirement checks exact issued IDs/ownership, retains data volumes and records,
stops the owned containers and removes only the credential-bearing relay
container. It does not revoke or change the user's source API key. The retired
trial cannot resume; a fresh attempt needs fresh preparation. Deadline watchdogs
can stop the exact worker/relay earlier when graceful/native cancellation fails;
unavailable termination remains a recorded gap, never a successful pass.
