"""Shared hashes, strict inventories and bounded native process execution."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory, exclude=(), root_exclude=()):
    result = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if relative.parts[0] in root_exclude or any(part in exclude for part in relative.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(f"Unexpected symlink in evidence inventory: {path}")
        if path.is_file():
            result[relative.as_posix()] = digest(path)
    return result


def run_turn(command, prompt, cwd, timeout=1200):
    # Files avoid communicate() waiting on pipes inherited by descendants.
    with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        stdin.write(prompt.encode("utf-8"))
        stdin.seek(0)
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(Path(cwd).resolve().parent)}
        process = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr, cwd=cwd, env=env, **options)
        try:
            process.wait(timeout=timeout)
        except BaseException as error:
            try:
                if os.name == "nt":
                    result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    if result.returncode and process.poll() is None:
                        raise RuntimeError("Could not terminate native process tree.")
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            stdout.seek(0)
            stderr.seek(0)
            if isinstance(error, subprocess.TimeoutExpired):
                error.output = stdout.read().decode("utf-8", "replace")
                error.stderr = stderr.read().decode("utf-8", "replace")
            raise
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(command, process.returncode, stdout.read().decode("utf-8", "replace"), stderr.read().decode("utf-8", "replace"))


def collect_native_evidence(session_id, sessions, parent):
    paths = [parent]
    for path in sorted(Path(sessions).rglob("*.jsonl")):
        if path == parent:
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                meta = json.loads(handle.readline())
        except (OSError, ValueError):
            continue  # Unrelated sessions may be empty or still being written.
        if not isinstance(meta, dict) or meta.get("type") != "session_meta":
            continue
        value = meta.get("payload")
        for key in ("source", "subagent", "thread_spawn", "parent_thread_id"):
            value = value.get(key) if isinstance(value, dict) else None
        if value == session_id:
            paths.append(path)
    records = []
    for path in paths:
        record = {"path": str(path), "actions": [], "tool_records": [], "settings": []}
        with path.open(encoding="utf-8") as handle:
            header = json.loads(handle.readline())
            if not isinstance(header, dict) or header.get("type") != "session_meta" or not isinstance(header.get("payload"), dict):
                raise RuntimeError(f"Invalid native session metadata: {path}")
            meta = header["payload"]
            if not isinstance(meta.get("id"), str):
                raise RuntimeError(f"Missing native session identity: {path}")
            if path == parent and meta["id"] != session_id:
                raise RuntimeError(f"Native parent identity mismatch: {path}")
            record["id"], record["source"] = meta["id"], meta.get("source")
            events = [json.loads(line) for line in handle if line.strip()]
            if any(not isinstance(e, dict) or not isinstance(e.get("payload"), dict) or not isinstance(e.get("type"), str) for e in events):
                raise RuntimeError(f"Invalid native session event: {path}")
            own_turns = {event["payload"]["turn_id"] for event in events
                         if event["type"] == "event_msg" and isinstance(event["payload"].get("turn_id"), str)
                         and event["payload"].get("thread_id") == record["id"]}
            current_turn, calls = None, {}
            for event in events:
                payload = event.get("payload", {})
                if event["type"] == "turn_context" and not isinstance(payload.get("turn_id"), str):
                    raise RuntimeError(f"Invalid native turn identity: {path}")
                if event["type"] == "turn_context" or event["type"] == "event_msg" and payload.get("type") == "task_started":
                    current_turn = payload.get("turn_id") if isinstance(payload.get("turn_id"), str) else None
                kind = payload.get("type")
                if kind is not None and not isinstance(kind, str):
                    raise RuntimeError(f"Invalid native payload type: {path}")
                if event["type"] == "response_item":
                    if kind in {"function_call", "custom_tool_call"} and current_turn in own_turns and isinstance(payload.get("call_id"), str):
                        calls[payload["call_id"]] = current_turn
                    if (kind in {"function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output"}
                            and isinstance(payload.get("call_id"), str) and payload["call_id"] in calls):
                        record["tool_records"].append({"turn_id": calls[payload["call_id"]], "payload": {
                            k: payload[k] for k in ("type", "id", "call_id", "name", "namespace", "arguments", "input", "output") if k in payload}})
                if event["type"] == "turn_context" and current_turn in own_turns:
                    record["settings"].append({k: payload[k] for k in ("model", "effort", "approval_policy", "sandbox_policy", "cwd") if k in payload})
                if event["type"] == "event_msg" and payload.get("type") == "item_completed" and payload.get("thread_id") == record.get("id"):
                    item = payload.get("item")
                    if not isinstance(item, dict):
                        raise RuntimeError(f"Invalid native completed item: {path}")
                    if str(item.get("type", "")).lower() not in {"reasoning", "usermessage"}:
                        record["actions"].append({"turn_id": payload.get("turn_id"), "item": item})
        records.append(record)
    return records
