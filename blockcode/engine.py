"""One entry point for the server and the CLI: generate, validate and run a program."""

from __future__ import annotations

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


def run(store: ProjectStore, project: Project, program: Program, target: str) -> RunResult:
    from blockcode.validate import validate

    tables = table_map(project)
    # the same code the editor shows (R's Quarto header carries the project title)
    extra = {"title": project.title or project.name} if target == "r" else {}
    gen: Generated = generate(program, tables, target, **extra)
    blocking = [d for d in validate(program, tables, target, generated=gen)
                if d.severity == "error"]
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
    else:
        result = _execute(store, project, gen, target, result_names(program))
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
