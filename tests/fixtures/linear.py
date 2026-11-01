"""Local-only MCP fixture. Start with --state JSON --log JSONL --ledger Markdown.

The operator keeps state/log outside the agent-writable consumer. Tool arguments
never contain filesystem paths. This is not a Linear client or package runtime.
Operator-only _fixture state can disable writes or inject a lost create response
and a changed readback at specified creation counts. Controls are never exposed.
"""

import argparse
import json
from pathlib import Path
import sys


FIELDS = {
    "id": {"type": "string"}, "team": {"type": "string"}, "project": {"type": "string"},
    "title": {"type": "string"}, "description": {"type": "string"},
    "parentId": {"type": ["string", "null"]},
    "blockedBy": {"type": "array", "items": {"type": "string"}},
    "links": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "url": {"type": "string"}},
        "required": ["title", "url"], "additionalProperties": False}},
}
TOOLS = [
    {"name": "inspect_workspace", "description": "Read local Linear-style fixture context and issues. Optional id/query filters issues; no network.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "query": {"type": "string"}}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "save_work_item", "description": "Create/update an issue in the local fixture only. Supply destination on every call. Provided fields replace values, including lists; omitted fields are retained. Returns assigned ID/URL.",
     "inputSchema": {"type": "object", "properties": FIELDS, "required": ["team", "project"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}},
]


def invoke(name, arguments, state_path):
    state = json.loads(state_path.read_text(encoding="utf-8"))
    controls = state.get("_fixture", {})
    if name == "inspect_workspace":
        if set(arguments) - {"id", "query"} or any(not isinstance(v, str) for v in arguments.values()):
            raise ValueError("Expected optional string id/query")
        issues = state["issues"]
        if "id" in arguments:
            issues = [i for i in issues if i["id"] == arguments["id"]]
        if "query" in arguments:
            query = arguments["query"].casefold()
            issues = [i for i in issues if query in (i["title"] + "\n" + i["description"]).casefold()]
        return {**{k: v for k, v in state.items() if k != "_fixture"}, "issues": issues}
    if name != "save_work_item":
        raise ValueError("Unknown fixture tool")
    if controls.get("read_only"):
        raise ValueError("Write capability unavailable")
    if set(arguments) - FIELDS.keys():
        raise ValueError("Unsupported fields")
    if any(arguments.get(k) != state["destination"][k] for k in ("team", "project")):
        raise ValueError("Destination is outside this fixture")
    for key in ("id", "title", "description"):
        if key in arguments and not isinstance(arguments[key], str):
            raise ValueError(key + " must be a string")
    if "parentId" in arguments and arguments["parentId"] is not None and not isinstance(arguments["parentId"], str):
        raise ValueError("parentId must be a string or null")
    blockers = arguments.get("blockedBy", [])
    if not isinstance(blockers, list) or any(not isinstance(v, str) for v in blockers):
        raise ValueError("blockedBy must be a list of IDs")
    links = arguments.get("links", [])
    if not isinstance(links, list) or any(not isinstance(v, dict) or set(v) != {"title", "url"} or any(not isinstance(x, str) for x in v.values()) for v in links):
        raise ValueError("links must contain title/url strings")
    ids = {i["id"] for i in state["issues"]}
    if any(v not in ids for v in [*blockers, *([arguments["parentId"]] if arguments.get("parentId") else [])]):
        raise ValueError("Referenced issue does not exist")
    if "id" in arguments:
        matches = [i for i in state["issues"] if i["id"] == arguments["id"]]
        if len(matches) != 1:
            raise ValueError("Update requires one existing ID")
        issue = matches[0]
    else:
        if not arguments.get("title") or not arguments.get("description"):
            raise ValueError("Creation requires title and description")
        number = 1
        while f"FX-{number}" in ids:
            number += 1
        issue = {"id": f"FX-{number}", "url": f"https://fixture.invalid/issues/FX-{number}"}
        state["issues"].append(issue)
    issue.update(arguments)
    result = dict(issue)
    uncertain = "id" not in arguments and controls.get("error_on_create") == len(state["issues"])
    if uncertain:
        del controls["error_on_create"]
    if "id" not in arguments and controls.get("mismatch_on_create") == len(state["issues"]):
        issue["description"] += "\nUnexpected external edit."
        del controls["mismatch_on_create"]
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    if uncertain:
        raise OSError("Response lost after request; outcome unknown.")
    return result


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("state", "log", "ledger"):
        parser.add_argument("--" + name, type=Path, required=True)
    paths = parser.parse_args()
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "local-linear-fixture", "version": "0.1.0"}}
        elif method == "tools/list":
            controls = json.loads(paths.state.read_text(encoding="utf-8")).get("_fixture", {})
            result = {"tools": TOOLS[:1] if controls.get("read_only") else TOOLS}
        elif method == "ping":
            result = {}
        elif method == "tools/call":
            params = request["params"]
            name, arguments = params["name"], params.get("arguments", {})
            checkpoint = paths.ledger.read_text(encoding="utf-8") if name == "save_work_item" and paths.ledger.exists() else None
            try:
                data, failed = invoke(name, arguments, paths.state), False
            except (ValueError, KeyError, TypeError, OSError) as error:
                data, failed = {"error": str(error)}, True
            with paths.log.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"tool": name, "arguments": arguments, "ledger_before": checkpoint, "result": data, "isError": failed}) + "\n")
            result = {"content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data, "isError": failed}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "Unsupported method"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
