"""Export standalone code plus the data it needs.

    sql    → <name>.sql + db.sqlite      run with: sqlite3 db.sqlite < <name>.sql
    python → <name>.py  + data/*.csv     run with: python <name>.py
    r      → <name>.R, <name>.qmd + data/*.csv
"""

from __future__ import annotations

import shutil
from pathlib import Path

from blockcode.codegen import generate
from blockcode.ir import Project
from blockcode.project_io import ProjectError, ProjectStore


def used_tables(project: Project) -> list[str]:
    names: list[str] = []
    for b in project.program.walk():
        for t in ([b.field("table")] if b.type in ("from", "join") else []):
            if t and t not in names:
                names.append(t)
    return names


def export_project(store: ProjectStore, project: Project, target: str, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    tables = {t.name: t for t in project.tables}
    stem = project.name.replace("-", "_")
    written: list[Path] = []
    if target == "sql":
        gen = generate(project.program, tables, "sql")
        if not gen.ok:
            raise ProjectError("This program uses blocks that have no SQL version.")
        path = out / f"{stem}.sql"
        path.write_text(gen.code)
        db = out / "db.sqlite"
        shutil.copy(store.ensure_db(project.name), db)
        return [path, db]
    if target == "python":
        path = out / f"{stem}.py"
        path.write_text(generate(project.program, tables, "python").code)
        written.append(path)
    elif target == "r":
        path = out / f"{stem}.R"
        path.write_text(generate(project.program, tables, "r", quarto=False).code)
        qmd = out / f"{stem}.qmd"
        qmd.write_text(generate(project.program, tables, "r", quarto=True,
                                title=project.title or project.name).code)
        written += [path, qmd]
    else:
        raise ProjectError(f"Unknown target {target!r}")
    for name in used_tables(project):
        info = tables.get(name)
        if info:
            dest = out / info.file
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(store.dir(project.name) / info.file, dest)
            written.append(dest)
    return written
