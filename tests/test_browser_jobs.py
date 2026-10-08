"""Runs in the browser: the server hands out a job, the browser runs it and posts back what the
harness wrote, and the server explains it. A stand-in browser here runs each job exactly as
handed over (the same harness, with the data files fetched from their URLs) and must get the
same results as a run on the server."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockcode import build as b
from blockcode.server import create_app

needs_r = pytest.mark.skipif(shutil.which("Rscript") is None, reason="R is not installed")


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(tmp_path / "projects"))


def grouped(*steps):
    return b.from_("enrolments", b.join("courses", "course_id"),
                   b.group(["dept"], b.agg("avg", "grade", "avg_grade"), b.agg("count", None, "n")),
                   *steps)


def prog_json(*blocks):
    return json.loads(b.program(*blocks).model_dump_json())


def fetch_files(c, job, into: Path):
    for f in job["files"]:
        res = c.get(f["url"])
        assert res.status_code == 200, f
        (into / f["path"]).parent.mkdir(parents=True, exist_ok=True)
        (into / f["path"]).write_bytes(res.content)


def browser_python(c, job, tmp_path) -> dict:
    """Do what the Pyodide worker does, with this machine's Python."""
    work, bc = tmp_path / "work", tmp_path / "bc"
    work.mkdir()
    bc.mkdir()
    fetch_files(c, job, work)
    (bc / "program.py").write_text(job["code"], encoding="utf-8")
    (bc / "h.py").write_text(job["harness"], encoding="utf-8")
    proc = subprocess.run([sys.executable, str(bc / "h.py"), str(bc / "program.py"),
                           str(bc / "result.json"), json.dumps(job["names"])],
                          cwd=work, capture_output=True, text=True, timeout=60,
                          env={"MPLBACKEND": "Agg", "PATH": ""})
    return {"stdout": proc.stdout, "timed_out": False,
            "data": json.loads((bc / "result.json").read_text(encoding="utf-8"))}


def browser_r(c, job, tmp_path) -> dict:
    """Do what webR does: run the harness and send back its files and plot pages."""
    work, out = tmp_path / "work", tmp_path / "out"
    work.mkdir()
    out.mkdir()
    fetch_files(c, job, work)
    (out / "program.R").write_text(job["code"], encoding="utf-8")
    (out / "h.R").write_text(job["harness"], encoding="utf-8")
    proc = subprocess.run(["Rscript", "--vanilla", str(out / "h.R"), str(out),
                           ",".join(job["names"]), str(out / "program.R"), "png"],
                          cwd=work, capture_output=True, text=True, timeout=120)
    import base64
    pngs = sorted(out.glob("plot*.png"))
    return {"stdout": proc.stdout, "timed_out": False,
            "files": {f.name: f.read_text() for f in out.iterdir() if f.suffix in (".txt", ".csv")},
            "plots": [base64.b64encode(p.read_bytes()).decode() for p in pngs]}


def same(a: dict, b_: dict):
    for k in ("ok", "tables", "stdout", "code"):
        assert a[k] == b_[k], k
    assert len(a["plots"]) == len(b_["plots"])
    assert (a["error"] or {}).get("block_id") == (b_["error"] or {}).get("block_id")
    assert (a["error"] or {}).get("message") == (b_["error"] or {}).get("message")


PROGRAMS = {
    "plots": lambda: (grouped(), b.plot("bar", "out", "dept", "avg_grade"),
                      b.repeat("i", b.lit(2), b.print_(b.var("i")))),
    "error": lambda: (b.from_("enrolments", b.limit(2)),
                      b.foreach("row", b.var("out"), b.print_(b.math("/", b.lit(1), b.lit(0))))),
}


@pytest.mark.parametrize("key", list(PROGRAMS))
def test_python_in_the_browser_matches_the_server(c, tmp_path, key):
    c.get("/api/projects/school")
    prog = prog_json(*PROGRAMS[key]())
    job = c.post("/api/projects/school/job", json={"program": prog, "target": "python"}).json()["job"]
    assert job["names"] == ["out"] and job["timeout"] > 0
    raw = browser_python(c, job, tmp_path)
    here = c.post("/api/projects/school/finish",
                  json={"program": prog, "target": "python", "raw": raw}).json()
    same(here, c.post("/api/projects/school/run", json={"program": prog, "target": "python"}).json())


@needs_r
@pytest.mark.parametrize("key", list(PROGRAMS))
def test_r_in_the_browser_matches_the_server(c, tmp_path, key):
    c.get("/api/projects/school")
    prog = prog_json(*PROGRAMS[key]())
    job = c.post("/api/projects/school/job", json={"program": prog, "target": "r"}).json()["job"]
    assert "```" not in job["code"]  # just the R, not the Quarto document
    raw = browser_r(c, job, tmp_path)
    here = c.post("/api/projects/school/finish", json={"program": prog, "target": "r", "raw": raw}).json()
    same(here, c.post("/api/projects/school/run", json={"program": prog, "target": "r"}).json())


def test_extra_blank_pages_are_dropped(c):
    """webR hands back every page it drew; only the ones R counted as real plots are kept."""
    c.get("/api/projects/school")
    prog = prog_json(grouped(), b.plot("bar", "out", "dept", "n"))
    raw = {"stdout": "", "files": {"pages.txt": "1\n", "table_out.csv": "dept,n\nMaths,3\n",
                                   "rows_out.txt": "1\n"}, "plots": ["AAA", "BBB"]}
    res = c.post("/api/projects/school/finish", json={"program": prog, "target": "r", "raw": raw}).json()
    assert res["ok"] and res["plots"] == ["AAA"]
    assert res["tables"][0]["rows"] == [["Maths", 3]]


def test_a_program_with_a_problem_gets_no_job(c):
    c.get("/api/projects/school")
    plot = b.plot("hist", "out", "dept")
    prog = prog_json(grouped(), plot)
    res = c.post("/api/projects/school/job", json={"program": prog, "target": "python"}).json()
    assert "job" not in res
    assert res["result"]["error"]["kind"] == "Problem" and res["result"]["error"]["block_id"] == plot.id


def test_a_browser_timeout_is_explained(c):
    c.get("/api/projects/school")
    prog = prog_json(b.while_(b.lit(True), b.setvar("x", b.lit(1))))
    for target in ("python", "r"):
        res = c.post("/api/projects/school/finish", json={
            "program": prog, "target": target, "raw": {"stdout": "", "timed_out": True}}).json()
        assert res["error"]["kind"] == "Timeout"


def test_jobs_are_only_for_python_and_r(c):
    c.get("/api/projects/school")
    prog = prog_json(grouped())
    assert c.post("/api/projects/school/job", json={"program": prog, "target": "sql"}).status_code == 400


def test_only_table_files_can_be_fetched(c):
    c.get("/api/projects/school")
    assert c.get("/api/projects/school/files/data/students.csv").text.startswith("student_id,")
    for bad in ("project.json", "data/../project.json", "data/nope.csv", "../school/project.json"):
        assert c.get(f"/api/projects/school/files/{bad}").status_code == 404, bad


def test_runtime_config(c, monkeypatch):
    cfg = c.get("/api/runtime").json()
    assert cfg["run_in"] == "browser"
    assert cfg["pyodide"].endswith("/pyodide.mjs") and cfg["webr"].endswith("/webr.mjs")
    monkeypatch.setenv("BLOCKCODE_RUN_IN", "server")
    monkeypatch.setenv("BLOCKCODE_PYODIDE_URL", "/static/pyodide/pyodide.mjs")
    cfg = c.get("/api/runtime").json()
    assert cfg["run_in"] == "server" and cfg["pyodide"] == "/static/pyodide/pyodide.mjs"
