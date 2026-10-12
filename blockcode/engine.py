"""One entry point for the server and the CLI: generate, validate and run a program.

Programs run in one of two places. SQL always runs here (SQLite). Python and R run in the
visitor's browser when they can (Pyodide and webR, see web/src/runtime/): ``prepare_job`` hands
the browser the code, the harness around it and the tidied CSVs it reads, and ``finish`` turns
what the harness wrote into the same RunResult a run here would give, with errors pointing at
their blocks. ``run_in`` runs on this machine: the CLI, the tests and the web app's fallback.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from blockcode.codegen import generate
from blockcode.codegen.emitter import Generated
from blockcode.ir import Program, Project, TableInfo
from blockcode.project_io import ProjectStore
from blockcode.run import RunError, RunResult

BROWSER_TARGETS = ("python", "r")
# WebAssembly runs slower than a native Python or R, so a run in the browser gets this much longer
BROWSER_SLOWDOWN = 2


def result_names(program: Program) -> list[str]:
    names: list[str] = []
    for b in program.walk():
        if b.type == "from":
            n = b.field("name") or "out"
            if n not in names:
                names.append(n)
    return names


def check(program: Program, tables: list[TableInfo],
          target: str) -> tuple[Generated, RunResult | None]:
    """Generate the code; if a problem the editor shows would stop it running (or SQL can't
    express it), also return the result that says so."""
    from blockcode.validate import validate

    by_name = {t.name: t for t in tables}
    gen: Generated = generate(program, by_name, target)
    if target == "sql" and not gen.ok:
        first = next((d for d in gen.diagnostics if d.severity == "sql"), None)
        return gen, RunResult(target=target, ok=False, error=RunError(
            kind="NoSQL", message=first.message if first else "This program has no SQL version.",
            block_id=first.block_id if first else None))
    blocking = [d for d in validate(program, by_name, target, generated=gen)
                if d.severity == "error"]
    if blocking:
        d = blocking[0]
        return gen, RunResult(target=target, ok=False, error=RunError(
            kind="Problem", message=d.message, block_id=d.block_id,
            line=(gen.lines_for(d.block_id) or [None])[0] if d.block_id else None))
    return gen, None


def run(store: ProjectStore, project: Project, program: Program, target: str) -> RunResult:
    return run_in(store.dir(project.name), store.ensure_db(project.name), project.tables,
                  program, target)


def run_in(workdir: Path, db: Path, tables: list[TableInfo], program: Program,
           target: str) -> RunResult:
    """Run ``program`` from ``workdir`` (which holds ``data/*.csv``) against the SQLite ``db``."""
    gen, stopped = check(program, tables, target)
    if stopped is not None:
        return stopped
    names = result_names(program)
    if target == "sql":
        from blockcode.run.sql_runner import run_sql
        return run_sql(gen, db, names)
    if target == "python":
        from blockcode.run.python_runner import run_python
        return run_python(gen, workdir, names)
    if target == "r":
        from blockcode.run.r_runner import run_r
        return run_r(gen, workdir, names)
    raise ValueError(f"Unknown target {target!r}")


# ---- running in the browser -----------------------------------------------------------------


class JobFile(BaseModel):
    path: str  # where the program reads it, e.g. "data/enrolments.csv"
    text: str  # the tidied CSV


class Job(BaseModel):
    """Everything the browser needs to run a Python or R program itself."""

    target: str
    code: str  # the code to run (for R, the R inside the Quarto document's chunks)
    harness: str  # the same harness a run here uses
    names: list[str]  # the result variables to report as tables
    files: list[JobFile]
    timeout: float  # seconds


class Raw(BaseModel):
    """What running a Job in the browser produced."""

    stdout: str = ""
    cut: bool = False  # the browser stopped keeping printed output past the limit
    timed_out: bool = False
    data: dict | None = None  # Python: the harness's result.json
    files: dict[str, str] = Field(default_factory=dict)  # R: the harness's output files
    plots: list[str] = Field(default_factory=list)  # R: every plot page, as base64 PNGs


def prepare_job(workdir: Path, tables: list[TableInfo], program: Program,
                target: str) -> tuple[Job | None, RunResult | None]:
    """A Job for the browser, or the result that says why the program can't run."""
    if target not in BROWSER_TARGETS:
        raise ValueError(f"Only {' and '.join(BROWSER_TARGETS)} run in the browser")
    gen, stopped = check(program, tables, target)
    if stopped is not None:
        return None, stopped
    from blockcode.run import python_runner, r_runner

    if target == "python":
        code, harness, timeout = gen.code, python_runner.HARNESS, python_runner.TIMEOUT_S
        names = result_names(program)
    else:
        code, harness, timeout = r_runner.strip_quarto(gen)[0], r_runner.HARNESS, r_runner.TIMEOUT_S
        names = r_runner.safe_names(result_names(program))
    files = [JobFile(path=t.file, text=(workdir / t.file).read_text(encoding="utf-8"))
             for t in tables if (workdir / t.file).is_file()]
    return Job(target=target, code=code, harness=harness, names=names, files=files,
               timeout=timeout * BROWSER_SLOWDOWN), None


def finish(program: Program, tables: list[TableInfo], target: str, raw: Raw) -> RunResult:
    """Turn what a run in the browser produced into a RunResult, exactly as a run here would."""
    if target not in BROWSER_TARGETS:
        raise ValueError(f"Only {' and '.join(BROWSER_TARGETS)} run in the browser")
    gen, stopped = check(program, tables, target)
    if stopped is not None:
        return stopped
    from blockcode.run.sandbox import clip

    stdout = clip(raw.stdout, more=raw.cut)
    if target == "python":
        from blockcode.run.python_runner import TIMEOUT_S, interpret
        return interpret(gen, raw.data, stdout, timed_out=raw.timed_out,
                         timeout=TIMEOUT_S * BROWSER_SLOWDOWN)
    from blockcode.run.r_runner import interpret, safe_names
    return interpret(gen, safe_names(result_names(program)), raw.files, raw.plots, stdout,
                     timed_out=raw.timed_out)
