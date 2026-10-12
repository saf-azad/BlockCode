"""Runs in the browser: the server hands out a job (the code, the harness and the tidied CSVs),
the browser runs it and posts back what the harness wrote, and the server explains it. A
stand-in browser here runs each job exactly as handed over and must get the same results as a
run on the server."""

import base64
import json
import shutil
import subprocess
import sys

import pytest

from blockcode import build as b
from tests.test_server import client, school_files, school_tables

needs_r = pytest.mark.skipif(shutil.which("Rscript") is None, reason="R is not installed")


def grouped(*steps):
    return b.from_("enrolments", b.join("courses", "course_id"),
                   b.group(["dept"], b.agg("avg", "grade", "avg_grade"), b.agg("count", None, "n")),
                   *steps)


def prog_json(*blocks):
    return json.loads(b.program(*blocks).model_dump_json())


def post(c, path, prog, target):
    return c.post(path, data={"request": json.dumps({"program": prog, "target": target})},
                  files=school_files())


def write_files(job, into):
    for f in job["files"]:
        (into / f["path"]).parent.mkdir(parents=True, exist_ok=True)
        (into / f["path"]).write_text(f["text"], encoding="utf-8")


def browser_python(job, tmp_path) -> dict:
    """Do what the Pyodide worker does, with this machine's Python."""
    work, bc = tmp_path / "work", tmp_path / "bc"
    work.mkdir()
    bc.mkdir()
    write_files(job, work)
    (bc / "program.py").write_text(job["code"], encoding="utf-8")
    (bc / "h.py").write_text(job["harness"], encoding="utf-8")
    proc = subprocess.run([sys.executable, str(bc / "h.py"), str(bc / "program.py"),
                           str(bc / "result.json"), json.dumps(job["names"])],
                          cwd=work, capture_output=True, text=True, timeout=60,
                          env={"MPLBACKEND": "Agg", "PATH": "", "PYTHONPATH": ":".join(sys.path)})
    return {"stdout": proc.stdout, "timed_out": False,
            "data": json.loads((bc / "result.json").read_text(encoding="utf-8"))}


def browser_r(job, tmp_path) -> dict:
    """Do what webR does: run the harness and send back its files and plot pages."""
    work, out = tmp_path / "work", tmp_path / "out"
    work.mkdir()
    out.mkdir()
    write_files(job, work)
    (out / "program.R").write_text(job["code"], encoding="utf-8")
    (out / "h.R").write_text(job["harness"], encoding="utf-8")
    proc = subprocess.run(["Rscript", "--vanilla", str(out / "h.R"), str(out),
                           ",".join(job["names"]), str(out / "program.R"), "png"],
                          cwd=work, capture_output=True, text=True, timeout=120)
    pngs = sorted(out.glob("plot*.png"))
    return {"stdout": proc.stdout, "timed_out": False,
            "files": {f.name: f.read_text() for f in out.iterdir() if f.suffix in (".txt", ".csv")},
            "plots": [base64.b64encode(p.read_bytes()).decode() for p in pngs]}


def same(a: dict, b_: dict):
    for k in ("ok", "tables", "stdout"):
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
def test_python_in_the_browser_matches_the_server(tmp_path, key):
    c = client()
    prog = prog_json(*PROGRAMS[key]())
    job = post(c, "/api/job", prog, "python").json()["job"]
    assert job["names"] == ["out"] and job["timeout"] > 0
    assert {f["path"] for f in job["files"]} == {"data/courses.csv", "data/enrolments.csv",
                                                 "data/students.csv"}
    raw = browser_python(job, tmp_path)
    here = c.post("/api/finish", json={"program": prog, "target": "python",
                                       "tables": school_tables(c), "raw": raw}).json()
    same(here, post(c, "/api/run", prog, "python").json())


@needs_r
@pytest.mark.parametrize("key", list(PROGRAMS))
def test_r_in_the_browser_matches_the_server(tmp_path, key):
    c = client()
    prog = prog_json(*PROGRAMS[key]())
    job = post(c, "/api/job", prog, "r").json()["job"]
    assert "```" not in job["code"]  # just the R, not the Quarto document
    raw = browser_r(job, tmp_path)
    here = c.post("/api/finish", json={"program": prog, "target": "r",
                                       "tables": school_tables(c), "raw": raw}).json()
    same(here, post(c, "/api/run", prog, "r").json())


def test_jobs_carry_tidied_csvs():
    """The browser keeps each CSV as uploaded; the job carries the tidied one the code reads."""
    c = client()
    messy = "city;people\nParis;2.148.000\nLyon;NA\n".encode("cp1252")
    prog = prog_json(b.from_("cities"))
    job = c.post("/api/job", data={"request": json.dumps({"program": prog, "target": "python"})},
                 files=[("files", ("cities.csv", messy, "text/csv"))]).json()["job"]
    assert job["files"] == [{"path": "data/cities.csv", "text": "city,people\nParis,2148000\nLyon,\n"}]


def test_job_responses_are_compressed():
    c = client()
    res = post(c, "/api/job", prog_json(grouped()), "python")
    assert res.headers.get("content-encoding") == "gzip"


def test_code_blocks_run_in_the_browser_but_not_on_the_server(monkeypatch):
    monkeypatch.delenv("BLOCKCODE_ALLOW_RAW_CODE", raising=False)
    c = client()
    prog = prog_json(b.raw("python", "print('hello')"))
    assert post(c, "/api/run", prog, "python").json()["error"]["kind"] == "RawCodeBlocked"
    assert "print('hello')" in post(c, "/api/job", prog, "python").json()["job"]["code"]


def test_extra_blank_pages_are_dropped():
    """webR hands back every page it drew; only the ones R counted as real plots are kept."""
    c = client()
    prog = prog_json(grouped(), b.plot("bar", "out", "dept", "n"))
    raw = {"stdout": "", "files": {"pages.txt": "1\n", "table_out.csv": "dept,n\nMaths,3\n",
                                   "rows_out.txt": "1\n"}, "plots": ["AAA", "BBB"]}
    res = c.post("/api/finish", json={"program": prog, "target": "r",
                                      "tables": school_tables(c), "raw": raw}).json()
    assert res["ok"] and res["plots"] == ["AAA"]
    assert res["tables"][0]["rows"] == [["Maths", 3]]


def test_a_program_with_a_problem_gets_no_job():
    c = client()
    plot = b.plot("hist", "out", "dept")
    res = post(c, "/api/job", prog_json(grouped(), plot), "python").json()
    assert "job" not in res
    assert res["result"]["error"]["kind"] == "Problem"
    assert res["result"]["error"]["block_id"] == plot.id


def test_a_browser_timeout_is_explained():
    c = client()
    prog = prog_json(b.while_(b.lit(True), b.setvar("x", b.lit(1))))
    for target in ("python", "r"):
        res = c.post("/api/finish", json={"program": prog, "target": target, "tables": [],
                                          "raw": {"stdout": "", "timed_out": True}}).json()
        assert res["error"]["kind"] == "Timeout"


def test_printing_from_the_browser_is_clipped():
    from blockcode.run.sandbox import MAX_OUTPUT_CHARS

    c = client()
    prog = prog_json(b.print_(b.lit("x")))
    raw = {"stdout": "x" * (MAX_OUTPUT_CHARS + 10), "data": {"error": None, "tables": [],
                                                              "plots": []}}
    res = c.post("/api/finish", json={"program": prog, "target": "python", "tables": [],
                                      "raw": raw}).json()
    assert res["ok"] and len(res["stdout"]) < MAX_OUTPUT_CHARS + 100
    assert res["stdout"].endswith("(the rest of the output was cut)\n")


def test_jobs_are_only_for_python_and_r():
    c = client()
    prog = prog_json(grouped())
    assert post(c, "/api/job", prog, "sql").status_code == 400
    res = c.post("/api/finish", json={"program": prog, "target": "sql", "tables": [], "raw": {}})
    assert res.status_code == 400


def test_runtime_config(monkeypatch):
    monkeypatch.delenv("BLOCKCODE_RUN_IN", raising=False)
    c = client()
    cfg = c.get("/api/runtime").json()
    assert cfg["run_in"] == "browser" and c.get("/api/health").json()["run_in"] == "browser"
    assert cfg["pyodide"].endswith("/pyodide.mjs") and cfg["webr"].endswith("/webr.mjs")
    monkeypatch.setenv("BLOCKCODE_RUN_IN", "server")
    monkeypatch.setenv("BLOCKCODE_PYODIDE_URL", "/static/pyodide/pyodide.mjs")
    cfg = c.get("/api/runtime").json()
    assert cfg["run_in"] == "server" and cfg["pyodide"] == "/static/pyodide/pyodide.mjs"
