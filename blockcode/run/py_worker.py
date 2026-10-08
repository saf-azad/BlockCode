"""A warm Python for running learners' code quickly.

Starting Python and importing pandas and matplotlib takes about a second, longer than most
programs take to run. This worker does that once, then forks a fresh child for every run: the
child starts with everything imported and nothing left over from earlier runs.

The server talks to it over a pipe, one JSON line per job. Where ``os.fork`` isn't available
(Windows) or the worker misbehaves, ``run_job`` returns None and the caller starts a fresh
Python instead, as before.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
import time


class Pool:
    """One worker process shared by the server's threads. It runs one job at a time; a job that
    arrives while it's busy gets a fresh Python rather than waiting its turn."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.broken = not hasattr(os, "fork") or sys.platform != "linux"
        atexit.register(self.stop)

    def _start(self, env: dict) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "blockcode.run.py_worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, text=True, bufsize=1,
        )
        if self.proc.stdout.readline().strip() != "ready":
            raise RuntimeError("the Python worker didn't start")

    def run_job(self, job: dict, env: dict) -> str | None:
        """Run one job; returns "done", "timeout", "crashed", or None if the worker can't."""
        if self.broken or not self.lock.acquire(blocking=False):
            return None
        try:
            for _attempt in range(2):
                try:
                    if self.proc is None or self.proc.poll() is not None:
                        self._start(env)
                    self.proc.stdin.write(json.dumps(job) + "\n")
                    self.proc.stdin.flush()
                    reply = self.proc.stdout.readline()
                    if reply:
                        return json.loads(reply)["status"]
                except (OSError, ValueError, RuntimeError):
                    pass
                self.stop()
            self.broken = True
            return None
        finally:
            self.lock.release()

    def stop(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self.proc = None


POOL = Pool()


# ---- inside the worker process -------------------------------------------------------------------

def _child(job: dict) -> None:
    """In the forked child: run the harness on the job, with output going to files."""
    os.chdir(job["cwd"])
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)  # input() mustn't read the job pipe
    out = os.open(job["stdout"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.dup2(out, 1)
    os.dup2(out, 2)
    sys.stdout = open(1, "w", encoding="utf-8", buffering=1, closefd=False)
    sys.stderr = sys.stdout
    try:
        import numpy

        numpy.random.seed()  # don't hand every run the worker's random numbers
        sys.argv = [job["harness"], job["code"], job["out"], json.dumps(job["names"])]
        with open(job["harness"], encoding="utf-8") as f:
            src = f.read()
        exec(compile(src, job["harness"], "exec"), {"__name__": "__main__"})
    finally:
        sys.stdout.flush()
        os._exit(0)


def _serve() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot  # noqa: F401
    import pandas  # noqa: F401

    reply = sys.stdout
    sys.stdout = sys.stderr  # nothing but replies goes down the pipe
    reply.write("ready\n")
    reply.flush()
    for line in sys.stdin:
        job = json.loads(line)
        reply.flush()
        pid = os.fork()
        if pid == 0:
            _child(job)
        deadline = time.monotonic() + job["timeout"]
        status = "timeout"
        while time.monotonic() < deadline:
            done, code = os.waitpid(pid, os.WNOHANG)
            if done:
                status = "done" if os.WIFEXITED(code) and os.WEXITSTATUS(code) == 0 else "crashed"
                break
            time.sleep(0.005)
        else:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        reply.write(json.dumps({"status": status}) + "\n")
        reply.flush()


if __name__ == "__main__":
    _serve()
