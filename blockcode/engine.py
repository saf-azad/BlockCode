"""One entry point for the server and the CLI: generate, validate and run a program."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import BaseModel

from blockcode.codegen import generate
from blockcode.codegen.emitter import Generated
from blockcode.ir import Program, Project
from blockcode.project_io import ProjectStore
from blockcode.run import RunError, RunResult


def table_map(project: Project) -> dict:
    return {t.name: t for t in project.tables}


def result_names(program: Program) -> list[str]:
    names: list[str] = []
    for b in program.walk():
        if b.type == "from":
            n = b.field("name") or "out"
            if n not in names:
                names.append(n)
    return names


def check(project: Project, program: Program, target: str) -> tuple[Generated, RunResult | None]:
    """Generate the code; if something stops it running, also return the result that says so."""
    from blockcode.validate import validate

    tables = table_map(project)
    # the same code the editor shows (R's Quarto header carries the project title)
    extra = {"title": project.title or project.name} if target == "r" else {}
    gen: Generated = generate(program, tables, target, **extra)
    blocking = [d for d in validate(program, tables, target, generated=gen)
                if d.severity == "error"]
    result = None
    if target == "sql" and not gen.ok:
        first = next((d for d in gen.diagnostics if d.severity == "sql"), None)
        result = RunResult(target=target, ok=False, error=RunError(
            kind="NoSQL", message=first.message if first else "This program has no SQL version.",
            block_id=first.block_id if first else None))
    elif blocking:
        d = blocking[0]
        result = RunResult(target=target, ok=False, error=RunError(
            kind="Problem", message=d.message, block_id=d.block_id,
            line=(gen.lines_for(d.block_id) or [None])[0] if d.block_id else None))
    if result is not None:
        result.code = gen.code
    return gen, result


def run(store: ProjectStore, project: Project, program: Program, target: str) -> RunResult:
    """Run on this machine (the CLI, and the web app's fallback)."""
    gen, stopped = check(project, program, target)
    if stopped is not None:
        return stopped
    result = _execute(store, project, gen, target, result_names(program))
    result.code = gen.code
    return result


# ---- running in the browser -----------------------------------------------------------------
# The web app runs Python (Pyodide) and R (webR) in the learner's browser. The server prepares
# a job (the code, the harness around it and the data files it reads), the browser runs it and
# sends back what the harness wrote, and ``finish`` turns that into a RunResult exactly as a
# run on the server would.

BROWSER_TARGETS = ("python", "r")


class JobFile(BaseModel):
    path: str  # where the program expects it, relative to the project, e.g. "data/x.csv"
    url: str
    version: str  # changes when the file does, so the browser knows to fetch it again


class Job(BaseModel):
    target: str
    project: str
    code: str  # the code to run (for R, the Quarto document's chunks)
    harness: str
    names: list[str]
    files: list[JobFile]
    timeout: float


class Raw(BaseModel):
    """What came back from running a job in the browser."""
    stdout: str = ""
    timed_out: bool = False
    data: dict | None = None  # Python: the harness's result.json
    files: dict[str, str] = {}  # R: the harness's output files by name
    plots: list[str] = []  # R: every plot page, as base64 PNGs


def browser_job(store: ProjectStore, project: Project, program: Program,
                target: str) -> tuple[Job | None, RunResult | None]:
    gen, stopped = check(project, program, target)
    if stopped is not None:
        return None, stopped
    from blockcode.run import python_runner, r_runner

    runner = python_runner if target == "python" else r_runner
    code = gen.code if target == "python" else r_runner.strip_quarto(gen)[0]
    files = []
    base = store.dir(project.name)
    for t in project.tables:
        f = base / t.file
        if f.is_file():
            st = f.stat()
            files.append(JobFile(path=t.file, url=f"/api/projects/{quote(project.name)}/files/"
                                 f"{quote(t.file)}", version=f"{st.st_size}-{st.st_mtime_ns}"))
    # WebAssembly runs slower than a native Python or R, so allow it twice as long
    return Job(target=target, project=project.name, code=code, harness=runner.HARNESS,
               names=result_names(program), files=files, timeout=runner.TIMEOUT_S * 2), None


def finish(project: Project, program: Program, target: str, raw: Raw) -> RunResult:
    gen, stopped = check(project, program, target)
    if stopped is not None:
        return stopped
    if target == "python":
        from blockcode.run.python_runner import interpret
        result = interpret(gen, raw.data, raw.stdout, timed_out=raw.timed_out)
    else:
        from blockcode.run.r_runner import interpret
        result = interpret(gen, result_names(program), raw.files, raw.plots, raw.stdout,
                           timed_out=raw.timed_out)
    result.code = gen.code
    return result


def _execute(store: ProjectStore, project: Project, gen: Generated, target: str,
             names: list[str]) -> RunResult:
    if target == "sql":
        from blockcode.run.sql_runner import run_sql
        return run_sql(gen, store.ensure_db(project.name), names)
    if target == "python":
        from blockcode.run.python_runner import run_python
        return run_python(gen, store.dir(project.name), names)
    if target == "r":
        from blockcode.run.r_runner import run_r
        return run_r(gen, store.dir(project.name), names)
    raise ValueError(f"Unknown target {target!r}")
