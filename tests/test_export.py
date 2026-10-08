"""Exported files run on their own, outside BlockCode."""

import shutil
import sqlite3
import subprocess
import sys

import pytest

from blockcode.examples import school
from blockcode.export import export_project


def test_export_sql_runs_with_sqlite(store, tmp_path):
    project = store.load("school")
    files = export_project(store, project, "sql", tmp_path)
    sql = next(f for f in files if f.suffix == ".sql").read_text()
    rows = sqlite3.connect(tmp_path / "db.sqlite").execute(sql.rstrip().rstrip(";")).fetchall()
    assert rows[0][0] == "Mathematics"


def test_export_python_runs_standalone(store, tmp_path):
    project = store.load("school")
    project.program.blocks.append(
        __import__("blockcode.build", fromlist=["x"]).print_(
            __import__("blockcode.build", fromlist=["x"]).var("out")))
    files = export_project(store, project, "python", tmp_path)
    py = next(f for f in files if f.suffix == ".py")
    assert (tmp_path / "data" / "enrolments.csv").exists()
    proc = subprocess.run([sys.executable, py.name], cwd=tmp_path, capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "Mathematics" in proc.stdout


def test_export_only_copies_used_tables(store, tmp_path):
    project = store.load("school")
    project.program = school()["year_counts"]
    export_project(store, project, "python", tmp_path)
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == ["students.csv"]


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="R is not installed")
def test_export_r_runs_standalone(store, tmp_path):
    project = store.load("school")
    files = export_project(store, project, "r", tmp_path)
    r = next(f for f in files if f.suffix == ".R")
    assert any(f.suffix == ".qmd" for f in files)
    proc = subprocess.run(["Rscript", r.name], cwd=tmp_path, capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "Mathematics" in proc.stdout
