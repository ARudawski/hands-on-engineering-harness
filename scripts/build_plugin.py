"""Build a portable, skills-only plugin from canonical APM assets."""

import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import re
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS = {"route", "clarify-scope", "write-spec", "plan-slices", "plan-feature",
          "deliver-task", "research", "deliver-code", "implement-slice", "review-code"}
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
# All current canonical Markdown links use these two forms. Reject missing targets.
LINK = re.compile(r"(?<=\]\()([^\s)]+)(?=\))|(?m:^\[[^\]\n]+\]:[ \t]*)(\S+)")
RUNTIME = """# ChatGPT runtime adapter

Read [shared guidance](instructions/harness.instructions.md) before using any
workflow, including linked helpers. Then read the selected workflow and its
required references. Preserve all workflow stages, approval gates, scoped grants,
task records and evidence rules. Do not start a new workflow merely to read a helper.

For a fresh deliver-task General request, the initial task request authorizes
plan preparation only. Asking to reconcile, research or produce an output is
the requested goal, not an existing execution grant. Present the scoped plan and
end the turn for approval before executing it. Reuse an actual prior execution
grant covering those actions when one exists; do not infer it from the initial
task wording, local-only destination or availability of tools. Software routing
retains deliver-code's separate stage gates.

## Invocation and available capabilities

In ChatGPT, use @skill-name, for example @deliver-task or @route. The $ and / command
examples in canonical supporting instructions describe Codex and Claude Code;
translate them to @ mentions when giving ChatGPT examples. The bundled skills
directory is supporting content, not another installation or independent agents.

Use the active Work project directory for .tmp records; do not write task records
into the plugin's files. Load applicable user/project guidance from the active
project. Installing this plugin does not supply computer files, credentials,
connected services, shell access or independent sessions. Use only capabilities
actually available and authorized in this conversation. Missing filesystem/tools
or required review facilities leave dependent work pending; report that gap without
claiming completion. Advice and clarification may proceed within their own scope.

## Independent reviews

Native Codex/Claude agent registration is not assumed. For a required review, load
the exact [plan-reviewer](agents/plan-reviewer.agent.md) or
[code-reviewer](agents/code-reviewer.agent.md) contract, then create a fresh
independent session adopting that named contract. Supply the contract itself,
applicable guidance, task scope/specification, actual artifact/comparison and check
evidence. The reviewer must actually read its required context and remain
inspection-only; do not ask it to edit, build, publish or delegate. Those limits
are an instruction contract, not a separate permission sandbox.

Resume the same reviewer session for corrections while its basis remains valid.
Missing independent sessions, essential context, comparison or checks means an
incomplete review and blocks the dependent stage. Never substitute parent
self-review or a different role. This adapter changes host invocation and role
loading only; it grants no execution, approval or external-write authority.
"""


def frontmatter(content, label):
    if not content.startswith("---\n") or "\n---\n" not in content[4:]:
        raise ValueError(f"invalid skill frontmatter: {label}")
    header, body = content[4:].split("\n---\n", 1)
    metadata = yaml.safe_load(header)
    if not isinstance(metadata, dict) or any(
        not isinstance(metadata.get(k), str) or not metadata[k].strip()
        for k in ("name", "description")
    ):
        raise ValueError(f"invalid skill metadata: {label}")
    return metadata, "---\n" + header + "\n---\n", body


def validate_links(files):
    """Check local Markdown references inside one exposed skill's complete bundle."""
    for name, content in files.items():
        if not name.endswith(".md"):
            continue
        for match in LINK.finditer(content.decode("utf-8")):
            target = next(g for g in match.groups() if g is not None)
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
            if target.startswith("/") or resolved.startswith("../") or resolved not in files:
                raise ValueError(f"invalid reference in {name}: {target}")


def rebase_links(body, skill):
    def replace(match):
        target = next(g for g in match.groups() if g is not None)
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            return match.group(0)
        updated = posixpath.normpath(f"references/harness/skills/{skill}/{target}")
        return match.group(0).replace(target, updated)
    return LINK.sub(replace, body)


def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    # Keep arbitrary output from overwriting repository inputs, even on rebuild.
    if output.is_relative_to(root) and not output.is_relative_to(root / ".tmp"):
        raise ValueError("output inside the repository must be under .tmp/")
    source = root / ".apm"
    required = [root / name for name in ("plugin.json", "LICENSE", "THIRD-PARTY-NOTICES.md")]
    required += [source / "instructions/harness.instructions.md"]
    required += [source / f"agents/{name}.agent.md" for name in ("plan-reviewer", "code-reviewer")]
    required += [source / f"skills/{name}/SKILL.md" for name in sorted(SKILLS)]
    for path in [source, *source.rglob("*"), *required]:
        if path.is_symlink():
            raise ValueError(f"symlink input is not allowed: {path}")
    for path in required:
        if not path.is_file():
            raise ValueError(f"missing required plugin/skill input: {path}")
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("$schema") != SCHEMA
            or manifest.get("name") != "hands-on-engineering-harness"
            or not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", "")))):
        raise ValueError("invalid plugin manifest schema, identity or version")
    actual = {p.parent.name for p in (source / "skills").glob("*/SKILL.md")}
    if actual != SKILLS:
        raise ValueError(f"unexpected skill set: {sorted(actual)}")
    canonical = {p.relative_to(source).as_posix(): p.read_bytes()
                 for p in sorted(source.rglob("*.md")) if p.is_file()}
    for name in sorted(SKILLS):
        content = canonical[f"skills/{name}/SKILL.md"]
        metadata, _, _ = frontmatter(content.decode("utf-8"), name)
        if metadata["name"] != name or len(content) > 1024 * 1024:
            raise ValueError(f"invalid skill identity or size: {name}")
    files = {p.name: p.read_bytes() for p in required[:3]}
    provenance = {name: hashlib.sha256(data).hexdigest() for name, data in canonical.items()}
    files["source-hashes.json"] = (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode()
    for name in sorted(SKILLS):
        _, header, body = frontmatter(canonical[f"skills/{name}/SKILL.md"].decode(), name)
        entry = (header + "\nRead [ChatGPT runtime guidance](references/harness/runtime.md) "
                 "and its shared guidance before following this workflow.\n" + rebase_links(body, name))
        local = {"SKILL.md": entry.encode(), "references/harness/runtime.md": RUNTIME.encode()}
        local.update({"references/harness/" + p: data for p, data in canonical.items()})
        validate_links(local)
        files.update({f"skills/{name}/{p}": data for p, data in local.items()})
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = build(ROOT, args.output)
    except (ValueError, OSError, yaml.YAMLError) as error:
        parser.exit(1, f"Plugin build failed: {error}\n")
    print(f"Built {output} (SHA256 {hashlib.sha256(output.read_bytes()).hexdigest()})")


if __name__ == "__main__":
    main()
