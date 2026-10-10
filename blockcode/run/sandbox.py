"""Light limits for the subprocesses that run a learner's Python or R.

This is not a full sandbox. On a shared server, the code a learner types runs with these
guards: a clean environment (no API keys or tokens from the server's own environment), a CPU
time limit, and a cap on the size of files it can write. Wall-clock timeouts are set by each
runner.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

try:
    import resource  # imported here: the preexec hook runs after fork and must not import
except ImportError:  # Windows
    resource = None  # type: ignore[assignment]

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_CHARS = 100_000  # printed output sent back to the browser
MAX_PLOTS = 12
# variables a Python or R child needs; everything else in the server's environment stays out
KEEP = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SYSTEMROOT", "R_HOME", "R_LIBS",
        "R_LIBS_USER", "R_LIBS_SITE", "LD_LIBRARY_PATH", "PYTHONPATH", "VIRTUAL_ENV")


def child_env(**extra: str) -> dict[str, str]:
    env = {k: os.environ[k] for k in KEEP if k in os.environ}
    tmp = tempfile.gettempdir()
    env.setdefault("PATH", os.defpath)
    env.setdefault("LANG", "C.UTF-8")
    env["HOME"] = tmp
    env["TMPDIR"] = tmp
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def limits(cpu_seconds: float):
    """A preexec_fn that caps CPU time and file size (POSIX only; None elsewhere)."""
    if resource is None:
        return None
    caps = []
    for which, value in ((resource.RLIMIT_CPU, int(cpu_seconds) + 1),
                         (resource.RLIMIT_FSIZE, MAX_FILE_BYTES)):
        _, hard = resource.getrlimit(which)
        caps.append((which, (value if hard == resource.RLIM_INFINITY else min(value, hard), hard)))

    def apply() -> None:
        for which, pair in caps:
            try:
                resource.setrlimit(which, pair)
            except (ValueError, OSError):
                pass

    return apply


def protect_server_process() -> None:
    """Stop other processes running as the same user (the learner's code) from reading this
    process's memory and /proc/<pid>/environ. Linux only; a no-op elsewhere."""
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        PR_SET_DUMPABLE = 4
        libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
    except Exception:  # noqa: BLE001 - best effort
        pass


class Captured(NamedTuple):
    stdout: str
    stderr: str
    timed_out: bool
    too_much: bool  # stopped for printing (or writing) too much


def _head(path: Path) -> str:
    with open(path, "rb") as f:
        raw = f.read(MAX_OUTPUT_CHARS * 4 + 1)
    text = raw.decode("utf-8", errors="replace")
    if len(text) > MAX_OUTPUT_CHARS or path.stat().st_size > len(raw):
        text = text[:MAX_OUTPUT_CHARS] + "\n… (the rest of the output was cut)\n"
    return text


def run_captured(cmd: list[str], cwd: Path, timeout: float, env: dict[str, str],
                 scratch: Path) -> Captured:
    """Run ``cmd`` with the limits above. Output goes to files in ``scratch`` (not pipes), so
    a program that prints forever can't fill the server's memory."""
    out_p, err_p = scratch / "stdout.txt", scratch / "stderr.txt"
    timed_out, code = False, 0
    with open(out_p, "wb") as out, open(err_p, "wb") as err:
        try:
            code = subprocess.run(cmd, cwd=cwd, stdout=out, stderr=err, timeout=timeout,
                                  env=env, preexec_fn=limits(timeout)).returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    xfsz = getattr(signal, "SIGXFSZ", None)
    too_much = (xfsz is not None and code == -xfsz) or out_p.stat().st_size >= MAX_FILE_BYTES
    return Captured(_head(out_p), _head(err_p)[-4000:], timed_out, too_much)
