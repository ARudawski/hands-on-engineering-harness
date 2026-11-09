# Isolated native feasibility checks

To resume authorized work in a different invoking chat, the trusted controller can
call `authorize_profile_handoff` with the original owner, target origin and exact
verified profile reference. This adds an immutable, origin-specific reuse grant;
it preserves the original owner and setup provenance. No credentials are read or
copied, and no old request, native root or approval checkpoint is adopted. The
native stdin interface cannot create grants. Missing grants and changed source
references remain rejected. Profile reuse does not establish current sign-in
validity or candidate isolation; those checks remain separate.

Opt-in developer tooling for evaluator outcome E01 / HAR-5. Ordinary package tests
exercise its model-free guards; they never launch Docker workers or models.
Complete bug workflows, private trial repositories and authoritative grading are
separate evaluator outcomes.

## Signed-in request boundary (HAR-12 S1)

The legacy request shape without a candidate returns `rejected_before_launch`
with `first_failure: deployment_unavailable`. It does not start Codex, access
authentication, run Docker or certify any native check. The isolated signed-in
candidate interface is described under [Connected candidate request](#connected-candidate-request-har-12-local-integration).

From the invoking Codex session, supply one JSON object on stdin:

```sh
python -c "import json,uuid; print(json.dumps(dict(request_id=str(uuid.uuid4()), case='native-foundation', seconds=900)))" | python tests/evaluation/signed_in.py
```

`CODEX_THREAD_ID` must be supplied by the trusted invoking session. No caller
origin or reply path is accepted in the payload. The fields are `request_id`
(canonical UUID), `case` (only `native-foundation`) and `seconds` (whole integer,
11 through 7200). Keep the same request UUID when redelivering that request;
changing its case or limit is rejected. The example generates a new request.
JSON is returned on stdout to that same caller, including the issued attempt,
trial, pinned harness revision, budget, first failure and skipped checks. Native
model and reviewer findings remain unknown/empty in this slice.

Private controller state lives at `.tmp/evaluation-signed-in/requests.sqlite3`.
The trusted controller owns this directory and the module; neither may be made
available to evaluated agents. Session origin is a correlation binding inside
this trusted channel, not authentication against a hostile local process.
SQLite transactions deduplicate requests and allow one launch claim. A claim
is bookkeeping only; this module contains no launcher. Future deployment work
must validate isolation before native dispatch.

One persisted elapsed budget starts at acceptance and includes preparation and
resume. Wall and monotonic deadlines both apply; a backward clock closes
admission. The final ten seconds are reserved for cleanup. Interrupt, expiry and
failed cleanup cannot reopen admission or replace the first failure; cleanup
failure is recorded separately. These are controller guards, not proof that a
native process was stopped. Every future native operation must honor them.

The recorder accepts only fixed event/status/failure enums and controller-verified
thread IDs. It drops free text, arbitrary errors, credential fields and foreign
thread events before serialization. It does not collect reviewer prose or native
history yet. Future adapters must sanitize those sources before any trace or
error write; the API route's raw stderr/whole-session collector is not suitable
for a shared signed-in store.

Run its credential-free checks with
`python -m unittest discover -s tests -p test_signed_in.py -v`.

### Native Windows preparation and diagnostic — HAR-12 S2 incomplete

The internal `--prepare` path also accepts an explicit `candidate_revision`
(full local commit SHA), optional `candidate_ref` label, and
`model="gpt-6-luna"`, `effort="low"`. Resolve a selected branch once with
`signed_in_candidate.resolve_candidate` in the trusted caller; the commit is
frozen into the request. Reusing a request with another candidate is rejected.
Preparation exports the complete committed tree, including unpublished local
feature commits, and uses an ordinary local-path stock-APM 0.35.0 dependency.
The full installation/export stays private. A separate candidate workspace copies
only its deployed `AGENTS.md`, `.agents/skills/` and `.codex/agents/` assets,
with hashes and role paths bound to the verified installation. The command gate
checks deployed reads and denied reads of actual grader/materialized answer files
in both its process and subprocess. Gate helpers are removed before case release.
Run candidate preparation with Python from the stock-APM 0.35.0 environment;
it reuses APM's YAML and content-hash helpers. No remote publication, sign-in or
model/account call is needed by the candidate installer.

Candidate provenance checks derive skills and roles from that commit and compare
the materialized package, deployed files/configuration and lockfile to it. They
impose no baseline skill count, reviewer names or instruction bodies. The receipt
records source/installed/compiled hashes and experiment options; native preparation
also records effective root configuration. This does not establish effective live
child configuration or behavior. The supported package mapping uses regular Git
files and a self-contained APM package; transitive package dependencies, unsupported
APM mappings return explicit limitations. Supported installed role model/effort
settings may differ from the requested root default. Unknown active configuration
is not silently admitted.

One actual candidate `--prepare` at `df2c4f4` completed in 7.281 seconds including
cleanup, using a fresh empty profile. The selected source/install provenance,
effective root configuration and command sandbox checks passed; native cancellation
took 1.515 seconds and the owned Job was empty. No model turn or evaluated case
was started. This establishes preparation for that candidate, not live reviewer
behavior or full HAR-12 acceptance.

The native diagnostic CLI restricts candidate input to preparation. Existing
scripted diagnostics retain their original fixed target; passing candidate input
to its `--diagnose` entry is rejected. The ordinary signed-in entry now has the
separate connected candidate path documented below.

An internal candidate observer now replaces fixed workflow phases on the selected
candidate path. Its opt-in `candidate_run` adapter is separate from the legacy
synthetic diagnostics (`LegacyWorkflowFixture`). A direct `candidate_run` flag
without a matching trusted delivery reservation is rejected before account access,
case materialization or model dispatch with `candidate_admission_unverified`.
The connected path binds the assessed executable/child-route evidence to the
actual root, installation, provider, permissions and enabled tools before case
release. Root canaries alone, payload flags and old receipts cannot admit a case.
It tracks native parent/child identities, turns/items, pending native decisions and
free-form agent messages. Reviewer names/counts, read commands, finding counts,
stage numbers and response JSON are not execution requirements. Ordinary work
under `.tmp/work` is permitted; supplied assessment inputs and installed candidate
assets remain immutable. The public task's assessment-only authority still applies.

Native questions/permission requests remain pending without an authorized answer;
this adapter has no general automatic reply policy. Natural-language requests are
retained for human assessment. A trusted post-turn assessment can identify a genuine
prose question and request an authorized answer on the same live root. Completed
assessments require no separate `finish` acknowledgement. The root completion time
is captured before that checkpoint; the reconciled artifact and its digest bind the
grade. Grading can finish after work cutoff on the original connection once native
cleanup is verified, without reopening candidate work. Genuine decision waits and
trusted assessment time are reported separately. Failed optional children remain
behavior warnings; recovered root work can still be graded when integrity holds.
Output reports task assessment (initially unassessed),
execution end, pending decisions, infrastructure limitations and cleanup separately.
Root completion alone does not establish child quiescence; native idle does not
establish Job cleanup, and forced cleanup does not establish task completion.

Paired scripted-event/stdio checks exercise these contracts without Codex inference.
One actual candidate-observer trial at `df2c4f4` completed through the ordinary
entry using existing managed sign-in. It passed the fixed sum-defect rubric and
verified normal-completion cleanup in67.930/300 seconds, including31.609 seconds
of identifiable controller waiting. Redelivery returned the same saved result
without relaunch. Root configuration reported Luna/low; one root and no children
were observed, with complete census and execution telemetry remaining unknown.
This case did not exercise native callback replies, continuation, disconnect or
active-descendant cancellation. Their retained source/component/replay evidence
does not become a new live demonstration. Subsequent review found answer hints
in its readable full APM package (`tests/evaluation/probes.py`). The recorded
answer and cleanup observations remain, but uncontaminated quality measurement
and the one-trial acceptance milestone are **not established**. No evidence shows
whether the model used those hints. The corrected private-install/workspace path
needs its own separately authorized scored trial; the earlier result cannot
validate it.

`signed_in_native.py` now uses a dedicated native Windows Codex process and MXC
command sandbox. It requires Codex's app-server APIs and native MXC enforcement,
Python, APM (`APM_BIN` can select it) and Git. Observed Codex/APM versions are
recorded for each attempt; version strings do not determine compatibility.
The actual install/inventory, protocol, effective configuration, sandbox canaries
and cleanup checks must pass. Missing capabilities stop preparation before a
model launch, with no unsandboxed fallback. Development checks use Python 3.11
and stock APM 0.35.0. The assessed harness source revision stays pinned so each
evaluation has a reproducible target. The native route does not
require Docker, an image ID or a copied authentication profile.

Python read grants come from the running interpreter's executable directory and
base installation; a virtual environment additionally needs its exact
`pyvenv.cfg` file. They grant no access to the virtual environment's parent.
One model-free preparation with Codex 0.167.0-alpha.3.2 and APM 0.35.0 passed
the full install, effective configuration, seven command controls and cleanup
in 8.593 seconds, including native cancellation in 1.531 seconds. This used a
fresh empty profile and no model/account call; it establishes preparation only.

Supply the same three-field stdin request as above, with an 11–900 second limit,
and choose one explicit mode:

The native request may additionally specify both `model` and `effort` together.
`--diagnose` requires that pair and a canonical `profile_id` registered by the
trusted invoking controller before allocating any work. `--prepare` also accepts
this six-field request while remaining model/account-free. An unknown, foreign,
changed or missing diagnostic profile is rejected; the shared user profile is
never selected as a fallback.
Explicit effort accepts `low` or `medium`; the selection overrides host defaults
for the root and both reviewer defaults, without editing the host profile.
It is frozen to the request ID, so re-delivery cannot change it. Installed role
files must not override these model settings; child metadata is checked too.

Profile registration is a trusted Python operation in `signed_in_profiles.py`,
using the completed dedicated-login receipt and its hash. Stdin accepts only the
profile UUID, never a home or credential path. The existing private SQLite store
keeps immutable origin-bound metadata: owned home, directory identity and setup
digest. Registration and validation never read or hash `auth.json`; normal token
refresh is allowed. Missing auth, changed directory identity, symlink aliases or
startup `.env`, `config.toml`, `AGENTS.md` or `requirements.toml` reject the
reference. These guarded dedicated homes use process-local configuration only.

The request freezes its profile reference alongside mode/model/effort and the
original budget. Every ordinary native send rechecks that binding; a model start
also requires the one-time launch claim and exact issued root. Cleanup admits
only stop/list/terminate operations and remains possible after profile drift.
The actual root is persisted once, and offline continuation intents must match
that root/profile. The public CLI does not expose resume or an evaluated case
runner. The explicit interaction adapter below is separate from these guards.
Bootstrap and interaction probes also freeze their purpose to the request, so
duplicate delivery cannot switch between them or start another attempt.
Native preparation explicitly selects the local execution environment and checks
its returned ID, cwd and workspace roots. The interaction checkpoint freezes that
actual environment identity; approval metadata may name it or omit the default,
but a different environment is rejected. The stored identity is hashed.
Attributed callback observations retain fixed booleans for diagnosis, without
copying raw commands, identifiers, request text or permission payloads.

```sh
python tests/evaluation/signed_in_native.py --prepare < private-request.json
```

`--prepare` cannot dispatch a model turn or account RPC. It uses a new empty
Codex home, full pinned APM install and unchanged reviewer definitions, checks
the effective native thread configuration, repeats synthetic file/network and
subprocess controls, and interrupts an active heartbeat command. The result is
`prepared_only` when these checks and cleanup pass; all live ACs remain skipped.
Its shared request ends closed with `missing_evidence` because no live evaluation
was attempted. Re-delivery returns that same receipt; it cannot promote the
request to a live run or reset its deadline.

The native controller and its command tools receive a process-local system-only
`PATH` selecting Windows PowerShell, with login shells disabled. The pinned CLI
resolves even absolute shell arguments by shell type, so an absolute tool
argument alone cannot select that executable. A competing `pwsh` on this path,
the CLI's PowerShell 7 fallback, or a Codex-home `.env` override blocks launch.
Preparation keeps its separate APM/Git environment; host settings and filesystem
grants are unchanged. The command gate and heartbeat now run through this system
PowerShell too. The failed bundled-shell startup was reproduced without a model;
the system-shell canary checks and command/descendant cancellation pass.

`--diagnose` implements the separately authorized synthetic bootstrap.
It uses the registered dedicated Codex-managed ChatGPT profile in the trusted controller, registers
the installed reviewers and supplies only public bootstrap context to a fresh
root. It runs no evaluated case. One Windows Luna/medium attempt authenticated
and performed model work, then its model-selected tool failed to resolve the
bundled PowerShell executable before the public probe ran. No reviewer or active
model-tree interrupt was reached. The direct command gate passing does not
validate this model tool path. The process-local shell-selection correction has
passed model-free preparation. A subsequent Luna/medium model run executed the
system-PowerShell preflight successfully, with all seven checks true. The
controller did not recognize the API's command display and rejected the first
plan-reviewer start while its boundary flag remained false. Both completed
reviewer assessments and the live interruption check remain unverified; that
incomplete result is retained without retry. Every native approval/escalation callback blocks the
diagnostic; it never grants broader host access. Fixed assessment-receipt codes
do not establish the substance of either review. Shared authentication/profile
cache isolation, alternate tools and complete context evidence remain open.

Command-display recognition now decodes the app-server's POSIX shell quoting
and compares the complete argument vector with the expected invocation. It does
not execute that display or accept substring matches. The root gate requires
its exact thread/turn, completed native command, integer exit0 and all expected
control booleans before reviewer admission. Model-free replay of the retained
public preflight and altered/foreign commands checked this correction before the
later bounded model runs summarized below.

A later bounded attempt stopped after the model copied a sentence-ending period
into the `preflight` argument. It exited before reviewer dispatch, with cleanup
verified. The bootstrap prompt now separates both exact commands from prose in
PowerShell code blocks; the worker and command guard still reject added
punctuation. A subsequent prompt-corrected run passed the model preflight and
both installed reviewers completed own actions and returned final assessments
with Luna/medium. The active-turn interrupt was acknowledged, but its native
descendant-stop/heartbeat check failed. Final attempt-owned Job cleanup and
independent stopped-PID/stable-heartbeat readback passed. That run remains
incomplete; it does not establish native-only cancellation or full acceptance.

The trusted cleanup path now follows an acknowledged turn interrupt with
targeted termination of the heartbeat's background terminal, when still listed.
It matches the issued thread, item, process identity and complete command;
unknown or ambiguous entries are never terminated. These terminal RPCs are
available to the controller only during diagnostic cleanup. They add no agent
permission or global configuration change.

PID exit and a full stable-heartbeat window are polled within the existing
ten-second cleanup allowance, reserving time for final Job closure and a second
independent stop observation. Forced Job shutdown cannot count as a native stop.
Short model-free tests cover late exit, surviving descendants, guarded terminal
selection and empty-list RPC availability. A separately authorized cancellation
mini-probe with Luna/low then exercised positive termination of a model-created
terminal: independent PID-exit and stable-heartbeat evidence passed in1.578
seconds before final Job closure, with no forced Job stop credited as native
success. Preparation, model work and cleanup took17.735 seconds of its60-second
cap. This private cancellation-only probe ran no reviewers or evaluated case;
all full acceptance checks remain skipped.

A later single combined synthetic run used the regular diagnostic with the root
and both installed reviewers at Luna/low. Both reviewers executed their own
commands and returned completed assessments. Targeted native termination,
independent PID/heartbeat stop before Job closure and final cleanup passed;
native cancellation took1.578 seconds and the whole invocation47.234 seconds of
its120-second cap. No retry or evaluated case ran. Scoped readback confirmed all
three actual model/effort contexts and the unchanged frozen consumer/runtime.
This establishes the combined bootstrap/cancellation path for that run, while
all full acceptance checks remain skipped. Clarification, native permission and
workflow decisions, exact resume, complete reviewer context/assessment substance
and shared cache/alternative-tool isolation evidence remain pending.

Trusted outer callers must cap the entire invocation at900 seconds, charge
preparation to that cap and retain elapsed timing on success or timeout. A
timeout is incomplete with cleanup unverified unless independently established.
Historical one-shot callers are retained with their original results; they are
not retry entry points.

One request budget includes APM/Git preparation and native work. Every subprocess
enters an attempt-specific kill-on-close Windows Job before its payload starts.
An independent watchdog closes admission and terminates that job at the cleanup
cutoff. Native interrupt, process/heartbeat checks and zero remaining job
processes are recorded separately. Missing cleanup evidence forces incomplete;
there are no automatic retries or changes to global Windows sandbox settings.

The model-free native command gate and installed `--prepare` path have passed on
Windows; this does not establish a signed-in feasibility pass. HAR-12/S3 remain
incomplete. The legacy `signed_in.py` request still rejects unavailable
deployment; candidate requests use the connected path below. Earlier experimental signed-in Docker work failed before observed
agent work; its subsequent profile-selection correction was never live retested.
Native preparation success does not validate that Docker route. The existing
API-backed tooling below remains a separate route.


### Focused native workflow fixture diagnostic

Internal `workflow_probe=True` and `parent_review_probe=True` diagnostics reuse the signed-in Windows
boundary with Luna/low. It first admits the exact root and both installed
reviewers using fresh bootstrap controls. Only then does a sandboxed helper
materialize the unchanged `native-foundation-v2` inputs used by the Docker worker.
Windows handles prevent input replacement while allowing the workflow's task
records; the controller never reads mutable fixture bodies. Hashes are checked
inside the sandbox, and handles are released after the owned Job is empty.

The root invokes the installed `deliver-task` skill for understanding only and
ends at its first approval gate. The parent then uses the real native
collaboration handlers through code mode to continue the original reviewers.
`parent_review_probe=True` selects a separate reviewers-only focus, without
repeating the workflow-understanding phase or granting workflow advancement.
The exact plaintext task actually received by each reviewer must match the
trusted task; opaque, extra, altered or foreign messages fail the check.
Exact participant/turn identities, own file reads, native skill/role context,
input integrity and bounded factual outputs are required. The private collector
grades actual child outputs; parent summaries cannot substitute for them.

This is an explicitly prompted fixture and structured approval presentation,
not proof of spontaneous workflow compliance or complete HAR-12 acceptance.
It grants no later workflow approval and performs no fixture implementation.
One authorized trial is limited to120 seconds including preparation and owned
Job cleanup, with no automatic retry. Job closure here makes no native
cancellation claim. This historical probe did not enable the public entry point;
the later connected path is described below. Failed or missing observations remain incomplete.

One focused trial finished in74.547 seconds with verified Job cleanup and
unchanged inputs/source. Fresh admission and the installed skill's stage1 pause
were observed, including its task record and requested stage2 approval. The
first direct reviewer continuation returned `native_rpc_failed` before a review
turn was acknowledged; no substantive fixture assessments were obtained. The
specific native rejection cause was not retained. This route is incomplete and
has not been retried; bootstrap reviewer assessments are separate evidence.

Inspected Codex source forbids
direct external input to parent-owned V2 sub-agents; resuming one does not
remove that restriction. This is source evidence, not a recovered AP29 error.
Direct child starts are now blocked by the controller as well. The native
`canAcceptDirectInput` value is retained as an observation, not used to permit
external child input. Only the bound root receives external turn starts, each
phase consuming one intent. Bootstrap and review tasks use native parent
CodeMode calls with exact received-message/history checks before acceptance.
Future RPC failures retain only a correlated native method, a known standard
numeric error code and fixed classification; native messages/data are omitted.

The opt-in fixture route sets process-local
`features.multi_agent_v2.non_code_mode_only=false` and namespace `collaboration`.
It also selects consistent native root/sub-agent usage hints for that capability;
the default native hint otherwise incorrectly says the handlers are absent from
code mode. Installed harness skills and reviewer role bodies remain unchanged.
A fresh, credential-free CLI
accepted `features.multi_agent_v2.non_code_mode_only=false` in a model-free
configuration check. Every fresh proof must admit the actual root and both
original roles with the seven existing nested tools plus the six native
collaboration handlers, unchanged OS/network/context boundaries and no unknown
tools. Before case release, each original child's received bootstrap task must
match; afterward its full two-task history, new turn, own reads and substantive
assessment must match. Initial native context is matched against this fresh
root's pre-first-turn context plus the exact original role. A valid known turn
boundary is mandatory; unknown initial fragments, forked history and any later
external user/developer/system input reject the proof. Raw context is not
retained in results. Source/configuration/model-free checks do not establish
actual tool exposure, plaintext delivery or reviewer behavior; those observations
remain pending the fresh explicitly authorized one-shot trial.

The parent-route one-shot stopped during bootstrap after37.265 seconds with
verified Job cleanup and unchanged executed source. Both direct children
completed their own read controls, but only one bootstrap assessment finished.
Reviewer/context/tool admission and fixture materialization were not reached;
no substantive fixture review or exact task-delivery proof was obtained. The
generic guard failure does not identify its triggering event. No retry occurred.
Later model-free metadata corrections add a trusted guard source location and
accurate reviewers-only case-dispatch flags; they are separate from that
archived executed candidate and have not been live-tested.

### Model-free checkpoints and guarded interaction transport

`signed_in_interactions.py` provides a trusted checkpoint helper around the existing
request store and an explicitly attached `NativeInteractions` transport adapter.
Neither is called by the public prepare/diagnose CLI; there is no evaluated dispatcher.
A trusted programmatic interaction probe reuses the same native preparation,
profile, process owner and result path for only question, exact resume and fixed
marker approval. It never launches the workflow fixture or reviewers. Its final
heartbeat cleanup is a native command check, not a model-active cancellation claim.
It binds an already-claimed request to one root and a frozen manifest hash, then
prepares at most one answer to the fixed public question. A matching native
resolution and completed question turn are required before preparing minimal
resume parameters for that exact root/checkpoint. Resume confirmation checks
the returned thread/checkpoint and the recomputed manifest before the next
phase. Reconstructing the helper preserves its consumed intents and deadline.

The permission phase prepares only one acceptance of the issued exact public
marker command in the bound consumer. It rejects changed commands/identities,
additional permissions and network requests. Offered execution/network policy
proposals are ignored: the response is always `accept` for this command, never
`acceptForSession` or a policy amendment decision. It requires
matching resolution plus same-item successful marker execution. Workflow
completion is held as `workflow_held_unassessed`, with no advancement method;
completion alone does not prove a real workflow approval pause. Request IDs are
single-use within their issuing connection. Confirmed reconnect opens a new
epoch because the native server restarts its request counter. Interrupt, expiry or clock rollback bars further
preparation. Only fixed states, verified UUIDs and hashes are persisted.

The adapter uses the actual thread/start response, bound profile/root, explicit
Luna/low selection, frozen effective metadata/lineage and a recomputed source,
consumer and startup fingerprint. It sends only the three fixed probes. Replies
require an exact callback captured on that connection, even when received before
turn/start acknowledgement. Under the owner lock it validates guards, commits
the single-use intent and removes the callback token, then writes outside the lock.
Uncertain delivery cannot retry. Default native callback rejection and raw
response/resume rejection remain intact.

At the completed question checkpoint it closes only the app-server connection,
requires that owned process to exit, and reconnects once under the same Job,
request and deadlines. After initialization, it sends the saved threadId with `excludeTurns: true`
to thread/resume. Effective metadata and the exact completed history must match.
Paginated history is read once through the exact-root `thread/turns/list` API,
with a persisted request identity, no item contents and a limit derived from the
known turn count. The actual resume response stays unchanged. The checkpoint
validator receives the actual page explicitly and requires complete known turns;
missing, extra-page, duplicate, unfinished or foreign history blocks continuation. There is
no fork, override, new root or budget reset, and no restart after disconnect failure.

Fabricated-event and scripted local Python stdio checks establish controller IO
and failure guards, not observed Codex questions, permissions or reconnects. The
scripted sequence includes a real benign marker subprocess in its owned Job.
No new Codex/model/account operation was performed for these wire tests. Full
tool/context evidence remains necessary before fixture release; the legacy
request still rejects deployment_unavailable and the later connected path checks
its actual root before releasing a case.

Earlier signed-in diagnostics retained a shared managed Codex home. Redirecting
SQLite alone would not isolate all session/config/cache state. In the retained
combined run, the V2 tool declarations for both reviewers also still included
delegation tools despite the configured depth limit. Those declarations are
not proof of effective authorization or denial. Full fresh-state/context and
every enabled tool/delegation route must be verified before evaluated work.

A separate auth-only setup has since succeeded with a newly created, verified
empty profile and normal user-authorized ChatGPT login. Its controller could
send only login/status/cancel methods; no thread, model, tool or reviewer could
start through it. Credentials were created by Codex in that dedicated profile
and were not copied from the existing user profile. A private prepare-only
specialization then used the signed-in profile with a fresh pinned installation:
all seven command controls, effective metadata and command/descendant cleanup
passed in8.391 seconds of a60-second cap. All full ACs remain skipped. This is
authentication/preparation evidence; neither reviewer nor any model turn ran in
that profile. The public native request path now binds the registered dedicated
profile and has passed one full model-free preparation in8.765 seconds of a
60-second cap, including native command cleanup. Exact duplicate delivery
returned the first receipt; changed mode/model/profile or foreign origin were
rejected without constructing a process owner.

One subsequent synthetic diagnostic exercised that binding with the actual root
and both original installed reviewers at Luna/low. Both reviewers performed own
commands and returned completed assessments; their native developer messages
contained the full original role instructions. All three recorded the same
explicit filesystem policy and expected permission profile. Native interruption,
targeted terminal termination, independent PID/heartbeat stop and final Job
cleanup passed; cancellation took1.578 seconds, the whole run42.125 seconds of
its120-second cap. No retry or evaluated case ran. These are attributable
bootstrap/reviewer/cancellation observations, with all full ACs still skipped.
Declared tools and policy consistency do not establish denial through every
effective route. Complete tool/context/lineage isolation, fixture assessment
substance, real interactions and exact resume remain pending.

A later focused native probe on Codex 0.167.0-alpha.3.2 completed the fixed
question with the Alpha answer and reopened the same root/checkpoint through
the bounded turn-history API. It stopped at the marker approval after 16.172
seconds; matching native source/metadata identified a rejected environment ID
as a contract mismatch. After the environment-binding correction, a separately
authorized probe repeated the question and same-root resume in17.390 seconds.
Captured callback flags confirmed the exact command/cwd/environment and an
offered policy proposal; the controller rejected that proposal metadata before
replying. It now ignores offered proposals and selects only once-only `accept`,
with model-free regression coverage. Both actual runs cleaned up within their
120-second bounds. Marker execution and the full workflow remain unverified;
there has been no model run after the policy-proposal correction.

A separately authorized corrected interaction probe then completed the native
question, same-root resume and approved marker execution in21.828 seconds,
including verified cleanup. It is a narrow interaction observation; full
isolation and all evaluated acceptance checks remain open. An internal opt-in
isolation diagnostic reuses native preparation and frozen request/profile
identity, asks the root and installed reviewers for actual nested-tool inventory
and read-only synthetic canaries, and exercises native patching against task and
synthetic protected files. It never replies to broader approval requests. Its
source/tests alone do not establish isolation or authorize evaluated dispatch.
The supported local goals feature is disabled because it is unused by these
trials. A separate read-only isolation-routes diagnostic can inspect complete
MCP server status for its own root before inference and requires no enabled
servers; the default transport cannot make that call. Actual tool inventories
and inherited permissions still require assessment on the tested deployment.
An actual isolation diagnostic observed matching root/reviewer policies,
roles, native inventories and protected-read controls. Its permitted native patch
completed; a protected synthetic patch reached a withheld approval callback and
all protected hashes stayed unchanged. A separate read-only route probe verified
an empty MCP status and removed goal tools on the root, then ended before the
reviewers started. A later explicitly authorized, prompt-corrected probe completed
both original reviewers' own inspections in45.390 seconds of a120-second limit.
Root and both reviewers had matching permissions/context, the same seven actual
nested tools and no goal tools. MCP status was empty before inference; cleanup
was verified in1.563 seconds. These observations close the current reviewer gap
for the inspected setup. They do not establish universal isolation or full HAR12
acceptance; the continuous primary fixture and seeded assessments remain pending.
No diagnostic was automatically repeated or relabeled.

Run the credential-free readiness checks with
`python -m unittest discover -s tests -p 'test_signed_in_*.py' -v`.

## Existing API-backed feasibility route

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
# Connected candidate request (HAR-12, local integration)

The trusted invoking chat can use `python tests/evaluation/signed_in.py` with a
JSON-lines stdin/stdout connection. The first line selects one candidate and an
existing profile authorized for that chat; `CODEX_THREAD_ID` supplies the origin:

```json
{"request_id":"<fresh UUID>","case":"native-foundation","seconds":120,"candidate_ref":"feature/example","profile_id":"<registered profile UUID>"}
```

Use `candidate_revision` instead of `candidate_ref` for an immutable40-character
SHA. Supported budgets are11–900 seconds, including preparation, connected
waiting and cleanup; the final ten seconds are reserved for cleanup. The branch
is resolved once. Repeating the identical request retrieves the first receipt
or existing progress without resolving its new tip, opening the account or
launching another trial. Changed input or a foreign origin is rejected.

The candidate path supports only the assessed Windows executable and generated
authority configuration. It verifies the actual fresh root, full stock-APM
installation, managed ChatGPT route, permissions and command controls before
creating the public case. Unsupported binaries/configurations or extra tools
yield a specific prelaunch blocker. It reuses the authenticated profile; it
does not sign in again. Installed role model/effort settings can vary. Reported
thread settings are configuration; unavailable execution telemetry and complete
subagent census remain unknown.

While connected, stdout emits checkpoint objects containing origin, request,
checkpoint UUID, kind, thread/turn IDs and a trusted-controller `body`. Assessment
bodies contain a private rubric and must never be forwarded to the candidate. The invoking
chat replies with those same identity fields, omitting `body` and adding a
`response`. A native question takes `{"answers":{"<question id>":{"answers":["<answer>"]}}}`.
Permission requests are forwarded, but this interface cannot expand the fixed
trial boundary: command/file callbacks support explicit `decline` or `cancel`;
a permissions callback supports an empty turn-scoped grant. An attempted
expansion is rejected. No approval is supplied automatically.

A completed root produces an `assessment` checkpoint with its reconciled artifact,
completion timestamp/digest and private rubric. Reply with
`{"verdict":"pass|fail|unassessed","reason":"<supported rationale>"}` to finish the
assessment directly. If the answer genuinely awaits a decision, reply with
`{"status":"waiting","question":"<unresolved question>"}` instead. Only then does
an `operator_decision` checkpoint accept
`{"action":"continue","text":"<authorized answer>"}` on that same live root inside
the original budget. Continuation retires the old artifact/grade. This supports
ordinary harness stage approvals without prescribing a workflow or requiring a
separate finish acknowledgement. Stale/foreign replies are rejected. EOF closes admission and cleans
up; reconnect recovery is deferred. An origin/request-bound
`{"origin":"<chat UUID>","request_id":"<request UUID>","action":"cancel"}` can cancel
an active connection.

Each completion grades only messages attributable to its current root turn.
Earlier root messages are separately identified as assessment context and remain
in private evidence. An empty completed follow-up is unassessed; its predecessor's
answer cannot substitute for missing output. A failed root ends as `failed` once
queued events and metadata confirm quiescence, with `candidate_failed` as the
cleanup stop reason. Active descendants, unresolved decisions and unfinished
successful work still prevent quiescence.

Grades remain provisional until cleanup and integrity checks succeed. If the
assessor misses the work cutoff, native work stops; the original unanswered
assessment identity can still receive a grade for that same frozen artifact on
the connected channel. A postcleanup question remains unassessed and cannot
reopen native work. A missing review connection retains an
unassessed first result. The final `result` is retained in the private request
store with identities, elapsed time, genuine decision waits, separate trusted
assessment time, root completion evidence, participant
observations, answer, quality judgment and cleanup. Unobserved waits are marked
unknown. Failed cleanup prevents acceptance; a wrong answer can be a valid
measurement.

Final reports contain one copy of the current answer under `deliverable`;
`completion` contains its identity, digest and timing metadata. The channel checks
the whole encoded JSON result against its131072-byte limit. Oversize results omit
bulk details, set `details_omitted: true`, and retain request/attempt/candidate
identity, outcome, timing, assessment, cleanup and the existing `evidence` path.
Read that private native receipt for full output/history; the original full
delivery result stays in the request store. Duplicate retrieval uses the same
bounded projection without relaunch or rewriting old receipts. Other checkpoint
messages retain their size validation and one-use authorization requirements.

Controlled transports cover the corrected protocol; a model-free native preparation
checks the private-install/deployed-view command boundary. The earlier real
signed-in trial used the old path. Its first answer identified both incorrect
sum examples and passed the fixed rubric; an additional mistaken comment about
the integer domain is retained as a behavior limitation. Normal completion and
cleanup were observed, but its readable full installation contained answer hints.
Clean quality measurement and trial acceptance remain unestablished; there is no
evidence whether those hints were used. No scored trial of this correction has
run. The earlier active-descendant stop evidence covers only
its validated mechanism. Starting another trial requires new scoped execution
authorization. Legacy requests without a candidate still return the existing
deployment-unavailable result.
