import gzip
import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from blockcode import build as b
from blockcode.server import MAX_FILE, create_app

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = Path(__file__).parent.parent / "blockcode" / "data" / "sample"


def client():
    return TestClient(create_app())


def school_files(gz: bool = True) -> list[tuple[str, tuple[str, bytes, str]]]:
    out = []
    for p in sorted(SAMPLE.glob("*.csv")):
        data = p.read_bytes()
        name = p.name + (".gz" if gz else "")
        out.append(("files", (name, gzip.compress(data) if gz else data, "application/gzip")))
    return out


def school_tables(c) -> list[dict]:
    return [c.post("/api/tables", files={"file": (p.name, p.read_bytes(), "text/csv")}).json()["table"]
            for p in sorted(SAMPLE.glob("*.csv"))]


def run(c, program, target="sql", files=None):
    req = json.dumps({"program": program.model_dump() if hasattr(program, "model_dump") else program,
                      "target": target})
    return c.post("/api/run", data={"request": req}, files=files if files is not None else school_files())


def test_health_and_blocks():
    c = client()
    health = c.get("/api/health").json()
    assert health["ok"] is True and "r" in health
    types = {s["type"] for s in c.get("/api/blocks").json()["blocks"]}
    assert {"from", "join", "where", "group", "foreach", "plot"} <= types


def test_nothing_is_preloaded():
    c = client()
    assert c.get("/api/projects/school").status_code in (404, 405)
    assert c.get("/api/examples").status_code in (404, 405)


def test_inspect_reads_types_and_empties():
    c = client()
    r = c.post("/api/tables", files={"file": ("pets.csv", (FIXTURES / "pets.csv").read_bytes(), "text/csv")})
    assert r.status_code == 200
    cols = {c["name"]: c for c in r.json()["table"]["columns"]}
    assert cols["age"]["type"] == "int" and cols["age"]["empty"] == 2
    assert r.json()["table"]["name"] == "pets"


def test_inspect_tidies_awkward_files():
    c = client()
    semi = "city;country;population\nParis;France;2148000\nLyon;France;513000\n".encode()
    r = c.post("/api/tables", files={"file": ("Cities 2024.csv", semi, "text/csv")}).json()
    assert r["table"]["name"] == "cities_2024"
    assert [x["name"] for x in r["table"]["columns"]] == ["city", "country", "population"]
    assert any("semicolon" in n for n in r["notes"])

    latin = "ville,note\nCafé,3\nÉcole,4\n".encode("latin-1")
    r = c.post("/api/tables", files={"file": ("v.csv", gzip.compress(latin), "application/gzip")})
    assert r.status_code == 200 and r.json()["table"]["rows"] == 2

    for bad, msg in [(b"", "empty"), (b"PK\x03\x04rest", "Excel"), (bytes(range(256)) * 4, "CSV")]:
        r = c.post("/api/tables", files={"file": ("x.csv", bad, "text/csv")})
        assert r.status_code == 400 and msg in r.json()["detail"]


def test_inspect_rejects_huge_files():
    c = client()
    big = b"a\n" + b"1\n" * (MAX_FILE // 2 + 10)
    r = c.post("/api/tables", files={"file": ("big.csv", gzip.compress(big), "application/gzip")})
    assert r.status_code == 413


def test_generate_parse_and_erd_need_only_schemas():
    c = client()
    tables = school_tables(c)
    prog = b.program(b.from_("enrolments", b.join("courses", "course_id"), b.limit(5))).model_dump()
    gen = c.post("/api/generate-all", json={"program": prog, "tables": tables, "title": "T"}).json()
    assert "JOIN courses USING (course_id)" in gen["sql"]["code"]
    assert "merge(courses" in gen["python"]["code"]
    assert 'title: "T"' in gen["r"]["code"]

    edited = gen["sql"]["code"].replace("LIMIT 5", "LIMIT 2")
    r = c.post("/api/parse", json={"code": edited, "lang": "sql", "tables": tables, "previous": prog}).json()
    assert r["ok"]
    steps = r["program"]["blocks"][0]["stacks"]["steps"]
    assert steps[-1]["fields"]["n"] == 2
    assert steps[-1]["id"] == prog["blocks"][0]["stacks"]["steps"][-1]["id"]

    erd = c.post("/api/erd", json={"tables": tables}).json()
    links = {(link["one"], link["many"], link["column"], link["kind"]) for link in erd["links"]}
    assert links == {("students", "enrolments", "student_id", "1-*"),
                     ("courses", "enrolments", "course_id", "1-*")}


def test_run_sql_and_python_agree():
    c = client()
    prog = b.program(b.from_("enrolments", b.join("courses", "course_id"),
                             b.group(["dept"], b.agg("count", None, "n")), b.order("dept")))
    sql = run(c, prog, "sql").json()
    py = run(c, prog, "python").json()
    assert sql["ok"] and py["ok"]
    assert sql["tables"][0]["rows"] == py["tables"][0]["rows"]


def test_run_accepts_plain_uploads_and_reports_missing_tables():
    c = client()
    prog = b.program(b.from_("students", b.limit(2)))
    r = run(c, prog, "sql", files=school_files(gz=False)).json()
    assert r["ok"] and len(r["tables"][0]["rows"]) == 2
    r = run(c, prog, "sql", files=[]).json()
    assert not r["ok"]


def test_visitors_never_share_tables():
    c = client()
    pets = [("files", ("pets.csv", (FIXTURES / "pets.csv").read_bytes(), "text/csv"))]
    prog = b.program(b.from_("pets", b.limit(1)))
    assert run(c, prog, "sql", files=pets).json()["ok"]
    # the next request didn't send pets, so there is no pets table
    assert not run(c, prog, "sql", files=school_files()).json()["ok"]


def test_run_maps_error_to_block():
    c = client()
    p = b.print_(b.var("best"))
    prog = b.program(b.from_("enrolments", b.limit(2)), b.foreach("row", b.var("out"), p))
    r = run(c, prog, "python").json()
    assert not r["ok"]
    assert r["error"]["kind"] == "NameError"
    assert r["error"]["block_id"] == p.id
    assert "best is used before it has a value" in r["error"]["message"]


def test_raw_code_is_refused_unless_opted_in(monkeypatch):
    # Free-typed ("Code") blocks run arbitrary Python/R on the server, so by default /api/run
    # refuses any program that contains one, pointing at the block. Block-only programs still run,
    # and showing/exporting code is never affected.
    monkeypatch.delenv("BLOCKCODE_ALLOW_RAW_CODE", raising=False)
    c = client()
    raw = b.program(b.raw("python", "print('hi')\n"))
    r = run(c, raw, "python", files=[]).json()
    assert r["ok"] is False and r["error"]["kind"] == "RawCodeBlocked"
    assert r["error"]["block_id"] == raw.blocks[0].id

    blocks_only = b.program(b.from_("students", b.limit(3)))
    assert run(c, blocks_only, "sql").json()["ok"] is True

    # Showing and exporting the raw code keep working even when running it is off.
    gen = c.post("/api/generate-all",
                 json={"program": raw.model_dump(), "tables": []})
    assert gen.status_code == 200 and "print('hi')" in gen.json()["python"]["code"]
    exp = c.post("/api/export", data={"request": json.dumps(
        {"program": raw.model_dump(), "target": "python", "title": "x"})}, files=[])
    assert exp.status_code == 200


def test_runaway_output_is_cut_off(monkeypatch):
    monkeypatch.setenv("BLOCKCODE_ALLOW_RAW_CODE", "1")
    c = client()
    prog = b.program(b.raw("python", "while True:\n    print('x' * 1000)\n"))
    r = run(c, prog, "python", files=[]).json()
    assert not r["ok"]
    assert r["error"]["kind"] in ("Timeout", "TooMuchOutput")
    assert len(r["stdout"]) < 200_000


def test_learner_code_cannot_read_server_secrets(monkeypatch):
    monkeypatch.setenv("BLOCKCODE_ALLOW_RAW_CODE", "1")
    monkeypatch.setenv("BLOCKCODE_TEST_SECRET", "hunter2")
    c = client()
    prog = b.program(b.raw("python", "import os\nprint(os.environ.get('BLOCKCODE_TEST_SECRET'))\n"))
    r = run(c, prog, "python", files=[]).json()
    assert r["ok"] and "hunter2" not in r["stdout"]


def test_export_zips_code_and_data():
    c = client()
    prog = b.program(b.from_("students", b.limit(3))).model_dump()
    for target, expect in [("sql", {"my_analysis.sql", "db.sqlite"}),
                           ("python", {"my_analysis.py", "data/students.csv"}),
                           ("r", {"my_analysis.R", "my_analysis.qmd", "data/students.csv"})]:
        req = json.dumps({"program": prog, "target": target, "title": "My analysis"})
        r = c.post("/api/export", data={"request": req}, files=school_files())
        assert r.status_code == 200, r.text
        assert r.headers["content-disposition"].endswith(f'my_analysis-{target}.zip"')
        names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
        assert names == expect


def test_unusual_sql_explains_instead_of_crashing():
    c = client()
    tables = school_tables(c)
    for code in ["SELECT * FROM students ORDER BY 1", "SELECT * FROM students LIMIT -1",
                 "SELEC * FRM students", "", "DROP TABLE students"]:
        r = c.post("/api/parse", json={"code": code, "lang": "sql", "tables": tables})
        assert r.status_code == 200, code
        assert r.json()["ok"] is False or r.json()["program"] is not None


def test_a_broken_program_degrades_instead_of_crashing():
    c = client()
    weird = {"blocks": [{"id": "x", "type": "from", "fields": {"table": ["students"], "name": 3},
                         "inputs": {}, "stacks": {"steps": [{"id": "y", "type": "limit",
                                                             "fields": {"n": "lots"}}]}}]}
    r = c.post("/api/generate-all", json={"program": weird, "tables": school_tables(c)})
    assert r.status_code == 200
    assert set(r.json()) == {"sql", "python", "r"}
