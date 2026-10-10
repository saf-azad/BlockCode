"""Export standalone code plus the data it needs.

    sql    → <name>.sql + db.sqlite      run with: sqlite3 db.sqlite < <name>.sql
    python → <name>.py  + data/*.csv     run with: python <name>.py
    r      → <name>.R, <name>.qmd + data/*.csv
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from blockcode.codegen import generate
from blockcode.ir import Program, Project, TableInfo
from blockcode.project_io import ProjectError, ProjectStore


def used_tables(program: Program) -> list[str]:
    names: list[str] = []
    for b in program.walk():
        for t in ([b.field("table")] if b.type in ("from", "join") else []):
            if t and t not in names:
                names.append(t)
    return names


def export_project(store: ProjectStore, project: Project, target: str, out: Path) -> list[Path]:
    return export_files(store.dir(project.name), store.ensure_db(project.name), project.tables,
                        project.program, target, out, title=project.title or project.name,
                        stem=project.name)


def export_files(workdir: Path, db: Path, table_list: list[TableInfo], program: Program,
                 target: str, out: Path, title: str = "BlockCode", stem: str = "analysis"
                 ) -> list[Path]:
    """Write ``program`` as standalone code for ``target`` into ``out``, with the data it
    reads (copied from ``workdir``, or the SQLite ``db`` for SQL)."""
    out.mkdir(parents=True, exist_ok=True)
    tables = {t.name: t for t in table_list}
    stem = re.sub(r"\W+", "_", stem).strip("_") or "analysis"
    written: list[Path] = []
    if target == "sql":
        gen = generate(program, tables, "sql")
        if not gen.ok:
            raise ProjectError("This program uses blocks that have no SQL version.")
        path = out / f"{stem}.sql"
        path.write_text(gen.code, encoding="utf-8")
        dest = out / "db.sqlite"
        shutil.copy(db, dest)
        return [path, dest]
    if target == "python":
        path = out / f"{stem}.py"
        path.write_text(generate(program, tables, "python").code, encoding="utf-8")
        written.append(path)
    elif target == "r":
        path = out / f"{stem}.R"
        path.write_text(generate(program, tables, "r", quarto=False).code, encoding="utf-8")
        qmd = out / f"{stem}.qmd"
        qmd.write_text(generate(program, tables, "r", quarto=True, title=title).code,
                       encoding="utf-8")
        written += [path, qmd]
    else:
        raise ProjectError(f"Unknown target {target!r}")
    for name in used_tables(program):
        info = tables.get(name)
        if info:
            dest = out / info.file
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(workdir / info.file, dest)
            written.append(dest)
    return written
