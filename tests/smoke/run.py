"""Opt-in native smoke checks. Process success is not a behavioral assessment."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apm_support import isolated_apm_env, require_apm_version
from native_support import digest, inventory, run_turn

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROMPTS = json.loads((FIXTURES / "prompts.json").read_text(encoding="utf-8"))
ORDINARY = {"planning", "clarify-scope", "write-spec"}


def fixture_changes(before, after):
    added = after.keys() - before.keys()
    bytecode = {p: after[p] for p in sorted(added) if "__pycache__" in Path(p).parts and Path(p).suffix == ".pyc"}
    return {"added": sorted(added - bytecode.keys()), "deleted": sorted(before.keys() - after.keys()),
            "modified": sorted(p for p in before.keys() & after.keys() if before[p] != after[p]),
            "generated_bytecode": bytecode}


def inputs(case):
    fixtures = ("export.py", "ordinary-contract.md") if case in ORDINARY else ("export.py", "contract.md", "draft.md", "legacy-index.md")
    return {
        "package": {**{f".apm/{p}": h for p, h in inventory(ROOT / ".apm").items()}, "apm.yml": digest(ROOT / "apm.yml")},
        "driver": digest(Path(__file__)), "support": digest(ROOT / "tests/apm_support.py"),
        "native_support": digest(ROOT / "tests/native_support.py"),
        "fixtures": {p: digest(FIXTURES / p) for p in fixtures},
        "prompt": hashlib.sha256(PROMPTS[case].encode()).hexdigest(),
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def output_path(path, resume=False):
    path = path.resolve()
    if ROOT.is_relative_to(path) or (path.is_relative_to(ROOT) and not path.is_relative_to(ROOT / ".tmp")):
        raise ValueError("Output must be outside published source (inside project .tmp is allowed).")
    if not resume and path.exists() and any(path.iterdir()):
        raise ValueError("Fresh output directory must be empty; use explicit --resume for an existing run.")
    return path


def installed_hashes(consumer):
    paths = ["AGENTS.md"]
    paths += [f".codex/agents/{p.name.removesuffix('.agent.md')}.toml" for p in (ROOT / ".apm/agents").glob("*.agent.md")]
    paths += [f".agents/skills/{p.relative_to(ROOT / '.apm/skills').as_posix()}" for p in (ROOT / ".apm/skills").rglob("*") if p.is_file()]
    return {p: digest(consumer / p) for p in paths if (consumer / p).is_file()}


def prepare(case, out):
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"case": case, "kind": "ordinary" if case in ORDINARY else "targeted", "output_dir": str(out), "status": "incomplete",
                "inputs": inputs(case), "turns": [], "session_id": None, "perturbations": []}
    write_json(out / "manifest.json", manifest)
    source, consumer = out / "source", out / "consumer"
    source.mkdir()
    shutil.copytree(ROOT / ".apm", source / ".apm")
    shutil.copy2(ROOT / "apm.yml", source / "apm.yml")
    if inventory(source) != manifest["inputs"]["package"]:
        raise RuntimeError("Source export differs from candidate.")
    consumer.mkdir()

    def write(path, text):
        target = consumer / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    write("apm.yml", json.dumps({"name": "harness-smoke", "version": "0.0.0", "targets": ["codex", "claude"],
          "dependencies": {"apm": [{"alias": "harness", "path": str(source)}]}}))
    write(".gitignore", ".tmp/\napm_modules/\n")
    write("README.md", "# Synthetic CSV utility\nReturns rows as an in-memory CSV string.\n" if case in ORDINARY else "# Synthetic CSV preview\nPlanning only; no implementation.\n")
    shutil.copy2(FIXTURES / "export.py", consumer / "export.py")
    write("docs/export-contract.md", (FIXTURES / ("ordinary-contract.md" if case in ORDINARY else "contract.md")).read_text(encoding="utf-8"))
    write("consumer-settings.json", '{"keep": true}\n')
    if case not in ORDINARY:
        write(".tmp/csv-preview/spec.md", (FIXTURES / "draft.md").read_text(encoding="utf-8"))
        write(".tmp/csv-preview/evidence.md", "# E-17\nObserved export_csv writes every row into StringIO. No runtime checks were run.\n")
        index = (FIXTURES / "legacy-index.md").read_text(encoding="utf-8") if case == "resume-correction" else "- [Task specification](spec.md) — Draft and task state.\n- [Evidence E-17](evidence.md) — Source observation.\n"
        write(".tmp/csv-preview/index.md", index)
    env = isolated_apm_env(out / "apm-state")
    apm = os.environ.get("APM_BIN") or shutil.which("apm")
    if apm and Path(apm).is_file():
        apm = str(Path(apm).resolve())
    manifest["apm_version"] = require_apm_version(apm, env, consumer)
    for name, args in (("install", ["install", "--only", "apm"]), ("compile", ["compile", "--target", "codex"])):
        result = subprocess.run([apm, *args], cwd=consumer, env=env, capture_output=True, timeout=120)
        (out / f"apm-{name}.log").write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"APM {name} failed; see {out / ('apm-' + name + '.log')}")
    for skill in (ROOT / ".apm/skills").rglob("*"):
        if skill.is_file() and digest(consumer / ".agents/skills" / skill.relative_to(ROOT / ".apm/skills")) != digest(skill):
            raise RuntimeError("Installed skill differs from candidate.")
    for definition in (source / ".apm/agents").glob("*.agent.md"):
        name = definition.name.removesuffix(".agent.md")
        reviewer = tomllib.loads((consumer / f".codex/agents/{name}.toml").read_text(encoding="utf-8"))
        if reviewer["developer_instructions"] != definition.read_text(encoding="utf-8").split("---", 2)[2].strip():
            raise RuntimeError("Installed reviewer differs from candidate.")
    guidance = (source / ".apm/instructions/harness.instructions.md").read_text(encoding="utf-8").split("---", 2)[2].strip()
    if guidance not in (consumer / "AGENTS.md").read_text(encoding="utf-8"):
        raise RuntimeError("Compiled guidance differs from candidate.")
    if not (consumer / "docs/export-contract.md").is_file():
        raise RuntimeError("Fixture baseline link is invalid.")
    manifest["pristine_installed"] = installed_hashes(consumer)
    for path in ({"missing-reviewer": [".codex/agents/plan-reviewer.toml"], "missing-context": ["docs/export-contract.md"]}.get(case, [])):
        manifest["perturbations"].append({"path": path, "before": digest(consumer / path), "after": None})
        (consumer / path).unlink()
    manifest["runtime_installed"] = installed_hashes(consumer)
    manifest["baseline"] = inventory(consumer, (".git", ".tmp"))
    manifest["status"] = "prepared"
    write_json(out / "manifest.json", manifest)
    return manifest


def validate_resume(case, out, manifest):
    if manifest["case"] != case or manifest["output_dir"] != str(out) or manifest["inputs"] != inputs(case):
        raise ValueError("Run identity or candidate/driver/fixture hashes changed.")
    if installed_hashes(out / "consumer") != manifest["runtime_installed"]:
        raise ValueError("Installed inputs changed; do not reinstall into an active run.")
    if "baseline" in manifest:
        changes = fixture_changes(manifest["baseline"], inventory(out / "consumer", (".git", ".tmp")))
        if any(changes[k] for k in ("added", "deleted", "modified")):
            raise ValueError(f"Non-task fixture files changed before continuation: {changes}")
    if manifest["status"] not in {"prepared", "pending-assessment"}:
        raise ValueError("Failed/incomplete runs need investigation, not automatic continuation.")
    if manifest["turns"]:
        ids = {t["session_id"] for t in manifest["turns"]}
        if ids != {manifest["session_id"]} or not manifest["session_id"]:
            raise ValueError("Parent session identity mismatch.")
    if len(manifest["turns"]) >= 8:
        raise ValueError("Eight-turn scenario budget exhausted.")


def parse_events(output):
    events, notes, errors = [], 0, []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            if line.lstrip().startswith(("{", "[")):
                errors.append("Truncated or malformed CLI event; later valid events retained.")
            else:
                notes += 1
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str) or ("item" in event and not isinstance(event["item"], dict)):
            errors.append("Invalid CLI event shape; later valid events retained.")
            continue
        item = event.get("item", {})
        if str(item.get("type", "")).lower() != "reasoning":
            events.append(event)
    return events, notes, errors


def execute(out, manifest, reply=None):
    consumer = out / "consumer"
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("Codex CLI unavailable; model check incomplete.")
    number = len(manifest["turns"]) + 1
    prefix = out / f"turn-{number}"
    if any(out.glob(f"turn-{number}.*")):
        raise RuntimeError("Turn evidence already exists; refusing filename reuse.")
    location = f"\n\nThe project directory is {consumer}." if manifest["case"] in ORDINARY else f"\n\nThe active fixture worktree is {consumer}. Use that directory explicitly for local tool operations. Task writes are confined to its .tmp/csv-preview/. No implementation, project tests/builds, commits, pushes, external services or publication. Unrelated consumer settings and approved docs must remain unchanged."
    prompt = reply if reply is not None else PROMPTS[manifest["case"]] + location
    command = [codex, "exec", "-C", str(consumer), "--sandbox", "workspace-write"]
    if manifest["session_id"]:
        command += ["resume", manifest["session_id"]]
    command += ["--skip-git-repo-check", "--json", "-o", str(prefix.with_suffix(".last.md")), "-"]
    if not manifest["turns"]:
        manifest["codex_version"] = subprocess.check_output([codex, "--version"], text=True, stderr=subprocess.DEVNULL, timeout=30).strip()
    turn = {"number": number, "session_id": manifest["session_id"], "exit_code": None,
            "completed": False, "identity_ok": False}
    manifest["turns"].append(turn)
    manifest["status"] = "incomplete"
    manifest["attempt_in_progress"] = number
    write_json(out / "manifest.json", manifest)
    try:
        with prefix.with_suffix(".prompt.txt").open("x", encoding="utf-8") as handle:
            handle.write(prompt)
        try:
            result = run_turn(command, prompt, consumer)
            output, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            output, stderr, code = error.stdout or b"", error.stderr or b"", None
            output = output.decode("utf-8", "replace") if isinstance(output, bytes) else output
            stderr = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
            manifest["failure"] = "Native turn timed out; process-tree cleanup attempted."
        prefix.with_suffix(".stderr.log").write_text(stderr, encoding="utf-8")
        events, notes, parse_errors = parse_events(output)
        manifest["stdout_non_json_lines"] = notes
        write_json(prefix.with_suffix(".events.json"), events)
        ids = {e["thread_id"] for e in events if e.get("type") == "thread.started" and isinstance(e.get("thread_id"), str)}
        expected = manifest["session_id"]
        turn["identity_ok"] = len(ids) == 1 and (expected is None or ids == {expected})
        if turn["identity_ok"]:
            manifest["session_id"] = next(iter(ids))
        turn.update(session_id=manifest["session_id"], exit_code=code,
                    completed=any(e.get("type") == "turn.completed" for e in events))
        manifest["after"] = inventory(consumer, (".git", ".tmp"))
        manifest["fixture_changes"] = fixture_changes(manifest["baseline"], manifest["after"])
        manifest["preserved"] = not any(manifest["fixture_changes"][k] for k in ("added", "deleted", "modified"))
        if not manifest["preserved"]:
            manifest["failure"] = "Non-task fixture files changed; see fixture_changes."
        if parse_errors:
            manifest["failure"] = " ".join(sorted(set(parse_errors)))
        elif code == 0 and turn["completed"] and turn["identity_ok"] and manifest["preserved"]:
            manifest["status"] = "pending-assessment"
        elif "failure" not in manifest:
            manifest["failure"] = "Native turn failed, did not complete, or returned an unexpected parent identity."
    except BaseException as error:
        manifest["failure"] = type(error).__name__ + ": " + str(error)
        manifest["status"] = "incomplete"
        raise
    finally:
        manifest.pop("attempt_in_progress", None)
        write_json(out / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(PROMPTS))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Continue a prepared run or its exact recorded parent session.")
    parser.add_argument("--reply-file", type=Path, help="Operator-supplied reply after external stage assessment.")
    args = parser.parse_args()
    if args.resume and args.output_dir is None or args.reply_file and not args.resume:
        parser.error("--resume needs --output-dir; --reply-file needs --resume.")
    out = output_path(args.output_dir or ROOT / ".tmp/harness-evaluation/runs" / f"{args.case}-{uuid4().hex[:8]}", args.resume)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8")) if args.resume else prepare(args.case, out)
    validate_resume(args.case, out, manifest)
    if args.reply_file and (args.prepare_only or not manifest["turns"]):
        parser.error("Replies require an existing parent turn and model execution.")
    if not args.prepare_only:
        if manifest["turns"] and args.reply_file is None:
            parser.error("Existing parent turns require an externally assessed --reply-file.")
        manifest = execute(out, manifest, args.reply_file.read_text(encoding="utf-8") if args.reply_file else None)
    print(json.dumps({"output_dir": str(out), "status": manifest["status"], "session_id": manifest["session_id"]}))
    return 0 if manifest["status"] in {"prepared", "pending-assessment"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Smoke check incomplete: {error}", file=sys.stderr)
        raise SystemExit(1)
