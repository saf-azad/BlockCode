"""Projects on disk.

    projects/<name>/project.blockcode.json   program + table schemas
    projects/<name>/data/*.csv               the learner's CSVs (exports copy these)
    projects/<name>/db.sqlite                the same CSVs loaded as tables for SQL
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from blockcode.data_io import ingest, table_name_for
from blockcode.ir import Program, Project, TableInfo

SAMPLE_DIR = Path(__file__).resolve().parent / "data" / "sample"
PROJECT_FILE = "project.blockcode.json"


class ProjectError(ValueError):
    pass


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-").lower()
    if not cleaned:
        raise ProjectError("A project needs a name made of letters or numbers.")
    return cleaned


class ProjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def dir(self, name: str) -> Path:
        return self.root / safe_name(name)

    def db_path(self, name: str) -> Path:
        return self.dir(name) / "db.sqlite"

    def list(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.parent.name for p in self.root.glob(f"*/{PROJECT_FILE}"))

    def exists(self, name: str) -> bool:
        return (self.dir(name) / PROJECT_FILE).is_file()

    def create(self, name: str, title: str = "", sample: bool = True) -> Project:
        d = self.dir(name)
        if self.exists(name):
            raise ProjectError(f'A project called "{name}" already exists.')
        (d / "data").mkdir(parents=True, exist_ok=True)
        project = Project(name=d.name, title=title or name)
        if sample:
            for csv in sorted(SAMPLE_DIR.glob("*.csv")):
                shutil.copy(csv, d / "data" / csv.name)
                project.tables.append(ingest(d / "data" / csv.name, d, self.db_path(name)))
            from blockcode.examples import get

            project.program = get("department_grades")
        self.save(project)
        return project

    def load(self, name: str) -> Project:
        path = self.dir(name) / PROJECT_FILE
        if not path.is_file():
            raise ProjectError(f'There is no project called "{name}".')
        return Project.model_validate_json(path.read_text())

    def save(self, project: Project) -> None:
        d = self.dir(project.name)
        d.mkdir(parents=True, exist_ok=True)
        (d / PROJECT_FILE).write_text(project.model_dump_json(indent=2))

    def save_program(self, name: str, program: Program) -> Project:
        project = self.load(name)
        project.program = program
        self.save(project)
        return project

    def add_csv(self, name: str, filename: str, content: bytes) -> TableInfo:
        project = self.load(name)
        d = self.dir(name)
        table = table_name_for(filename)
        dest = d / "data" / f"{table}.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        try:
            info = ingest(dest, d, self.db_path(name), table)
        except Exception as exc:  # pandas raises many kinds of parse errors
            dest.unlink(missing_ok=True)
            raise ProjectError(f"That file doesn't look like a CSV I can read: {exc}") from exc
        project.tables = [t for t in project.tables if t.name != table] + [info]
        self.save(project)
        return info

    def ensure_db(self, name: str) -> Path:
        """Rebuild the SQLite DB from the CSVs if it is missing (e.g. a freshly copied project)."""
        db = self.db_path(name)
        if not db.exists():
            project = self.load(name)
            for t in project.tables:
                ingest(self.dir(name) / t.file, self.dir(name), db, t.name)
        return db
