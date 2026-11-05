"""Shared hashes, strict inventories and bounded native process execution."""

import hashlib
import os
from pathlib import Path
import signal
import subprocess
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory, exclude=()):
    result = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part in exclude for part in relative.parts):
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
