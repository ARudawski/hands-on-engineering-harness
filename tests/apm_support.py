"""Stock APM subprocess setup shared by packaging and optional smoke checks."""

import os
from pathlib import Path
import re
import subprocess


def isolated_apm_env(root, base_env=None):
    """Return a child environment with APM's user state inside root."""
    root = Path(root).resolve()
    env = dict(os.environ if base_env is None else base_env)
    for key, relative in {
        "HOME": "home", "USERPROFILE": "home", "APM_HOME": "home/.apm",
        "APPDATA": "home/AppData/Roaming", "LOCALAPPDATA": "home/AppData/Local",
        "XDG_CONFIG_HOME": "home/.config", "XDG_CACHE_HOME": "cache",
        "APM_CACHE_DIR": "cache/apm", "APM_TEMP_DIR": "tmp", "TMPDIR": "tmp", "TMP": "tmp", "TEMP": "tmp",
    }.items():
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    profile = Path(env["USERPROFILE"])
    env["HOMEDRIVE"] = profile.drive
    env["HOMEPATH"] = str(profile)[len(profile.drive):]
    env.pop("APM_NO_CACHE", None)
    return env


def require_apm_version(executable, env, cwd):
    """Require the stock version covered by these installation contracts."""
    guidance = "Install apm-cli==0.35.0 or set APM_BIN to its executable."
    if not executable:
        raise RuntimeError(f"APM executable unavailable. {guidance}")
    try:
        result = subprocess.run(
            [str(executable), "--version"], cwd=cwd, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Cannot check APM version: {error}. {guidance}") from error
    output = (result.stdout + result.stderr).strip()
    match = re.search(r"^Agent Package Manager \(APM\) CLI version (\S+)\s*$", output, re.MULTILINE)
    if result.returncode or not match or match[1] != "0.35.0":
        raise RuntimeError(f"APM checks require 0.35.0; version check exited {result.returncode}: {output!r}. {guidance}")
    return match[1]
