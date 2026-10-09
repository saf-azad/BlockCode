"""One entry point for the server and the CLI: generate, validate and run a program."""

from __future__ import annotations

from pathlib import Path

from blockcode.codegen import generate
from blockcode.codegen.emitter import Generated
from blockcode.ir import Program, Project, TableInfo
from blockcode.project_io import ProjectStore
from blockcode.run import RunError, RunResult


def result_names(program: Program) -> list[str]:
    names: list[str] = []
    for b in program.walk():
        if b.type == "from":
            n = b.field("name") or "out"
            if n not in names:
                names.append(n)
    return names


def run(store: ProjectStore, project: Project, program: Program, target: str) -> RunResult:
    return run_in(store.dir(project.name), store.ensure_db(project.name), project.tables,
                  program, target)


def run_in(workdir: Path, db: Path, tables: list[TableInfo], program: Program,
           target: str) -> RunResult:
    """Run ``program`` from ``workdir`` (which holds ``data/*.csv``) against the SQLite ``db``."""
    gen: Generated = generate(program, {t.name: t for t in tables}, target)
    blocking = [d for d in gen.diagnostics if d.severity == "error"]
    if target == "sql" and not gen.ok:
        first = next((d for d in gen.diagnostics if d.severity == "sql"), None)
        return RunResult(target=target, ok=False, error=RunError(
            kind="NoSQL", message=first.message if first else "This program has no SQL version.",
            block_id=first.block_id if first else None))
    if blocking:
        d = blocking[0]
        return RunResult(target=target, ok=False, error=RunError(
            kind="Problem", message=d.message, block_id=d.block_id,
            line=(gen.lines_for(d.block_id) or [None])[0] if d.block_id else None))
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
