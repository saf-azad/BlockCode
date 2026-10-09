"""Command line interface.

    blockcode new <project>                 create a project (with the school sample data)
    blockcode import-csv <project> <file>   add a CSV as a table
    blockcode code <project> --target sql   print the generated code
    blockcode validate <project> --target   list problems
    blockcode run <project> --target python run and print the result table
    blockcode export <project> --target r   write a standalone file (+ data)
    blockcode serve                         start the web editor
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from blockcode.project_io import ProjectError, ProjectStore

app = typer.Typer(help="BlockCode: blocks that compile to SQL, Python and R.",
                  no_args_is_help=True)

PROJECTS = typer.Option(Path("projects"), "--projects-dir", "-d", help="Where projects live.")
TARGET = typer.Option("sql", "--target", "-t", help="sql, python or r")
PROGRAM = typer.Option(None, "--program", "-p",
                       help="A .blockcode.json program or project file to use instead.")


def _load(store: ProjectStore, name: str, program_file: Path | None):
    try:
        project = store.load(name)
    except ProjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    if program_file:
        from blockcode.ir import Program, Project

        text = program_file.read_text()
        try:
            project.program = Project.model_validate_json(text).program
        except Exception:
            project.program = Program.model_validate_json(text)
    return project


def _check_target(target: str) -> str:
    if target not in ("sql", "python", "r"):
        typer.echo("--target must be sql, python or r", err=True)
        raise typer.Exit(2)
    return target


@app.command()
def new(name: str, projects_dir: Path = PROJECTS,
        empty: bool = typer.Option(False, help="Start without the school sample data.")) -> None:
    """Create a project."""
    try:
        p = ProjectStore(projects_dir).create(name, sample=not empty)
    except ProjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    typer.echo(f"Created {projects_dir / p.name} with tables: "
               f"{', '.join(t.name for t in p.tables) or '(none)'}")


@app.command("import-csv")
def import_csv(name: str, csv: Path, projects_dir: Path = PROJECTS) -> None:
    """Add a CSV to a project as a table."""
    try:
        info = ProjectStore(projects_dir).add_csv(name, csv.name, csv.read_bytes())
    except ProjectError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    typer.echo(f"Loaded {info.name}: {info.rows} rows")
    for c in info.columns:
        typer.echo(f"  {c.name:<20} {c.type:<6} {c.empty} empty" if c.empty else
                   f"  {c.name:<20} {c.type}")


@app.command()
def code(name: str, target: str = TARGET, projects_dir: Path = PROJECTS,
         program: Path | None = PROGRAM) -> None:
    """Print the generated code."""
    from blockcode.codegen import generate

    store = ProjectStore(projects_dir)
    project = _load(store, name, program)
    gen = generate(project.program, project.tables, _check_target(target))
    typer.echo(gen.code, nl=False)


@app.command()
def validate(name: str, target: str = TARGET, projects_dir: Path = PROJECTS,
             program: Path | None = PROGRAM) -> None:
    """List problems for a target. Exits 1 if there are errors."""
    from blockcode.validate import validate as check

    store = ProjectStore(projects_dir)
    project = _load(store, name, program)
    diags = check(project.program, {t.name: t for t in project.tables}, _check_target(target))
    for d in diags:
        typer.echo(f"{d.severity:<8} {d.block_id or '-':<8} {d.message}")
    if not diags:
        typer.echo("No problems.")
    if any(d.severity == "error" or (target == "sql" and d.severity == "sql") for d in diags):
        raise typer.Exit(1)


@app.command()
def run(name: str, target: str = TARGET, projects_dir: Path = PROJECTS,
        program: Path | None = PROGRAM) -> None:
    """Run the program and print the result."""
    from blockcode.engine import run as run_program

    store = ProjectStore(projects_dir)
    project = _load(store, name, program)
    result = run_program(store, project, project.program, _check_target(target))
    if result.stdout:
        typer.echo(result.stdout, nl=False)
    for t in result.tables:
        typer.echo(_format_table(t))
    if result.plots:
        typer.echo(f"({len(result.plots)} plot(s); use the web editor or export to see them)")
    if result.error:
        where = f" (line {result.error.line})" if result.error.line else ""
        typer.echo(f"Error{where}: {result.error.message}", err=True)
        raise typer.Exit(1)


@app.command()
def export(name: str, target: str = TARGET, projects_dir: Path = PROJECTS,
           out: Path = typer.Option(Path("export"), "--out", "-o", help="Output folder."),
           program: Path | None = PROGRAM) -> None:
    """Write standalone code (+ data files) to a folder."""
    from blockcode.export import export_project

    store = ProjectStore(projects_dir)
    project = _load(store, name, program)
    files = export_project(store, project, _check_target(target), out)
    for f in files:
        typer.echo(f"wrote {f}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the web editor. Each visitor's tables and blocks stay in their own browser."""
    import uvicorn

    from blockcode.server import create_app

    uvicorn.run(create_app(), host=host, port=port)


@app.command()
def version() -> None:
    """Print the BlockCode version."""
    from blockcode import __version__

    typer.echo(__version__)


def _format_table(t) -> str:
    cols = t.columns
    rows = [["" if v is None else (f"{v:.4g}" if isinstance(v, float) else str(v)) for v in r]
            for r in t.rows]
    widths = [max([len(c)] + [len(r[i]) for r in rows]) for i, c in enumerate(cols)]
    line = lambda vals: "  ".join(v.ljust(w) for v, w in zip(vals, widths))  # noqa: E731
    out = [line(cols), line(["-" * w for w in widths])] + [line(r) for r in rows]
    more = t.total_rows - len(t.rows)
    if more > 0:
        out.append(f"... {more} more rows")
    return "\n".join(out)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
