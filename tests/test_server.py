from pathlib import Path

from fastapi.testclient import TestClient

from blockcode import build as b
from blockcode.server import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def client(tmp_path):
    return TestClient(create_app(tmp_path))


def test_health(tmp_path):
    assert client(tmp_path).get("/api/health").json()["ok"] is True


def test_blocks_lists_specs(tmp_path):
    data = client(tmp_path).get("/api/blocks").json()
    types = {s["type"] for s in data["blocks"]}
    assert {"from", "join", "where", "group", "foreach", "plot"} <= types


def test_project_generate_run_upload(tmp_path):
    c = client(tmp_path)
    project = c.get("/api/projects/school").json()
    assert {t["name"] for t in project["tables"]} == {"students", "courses", "enrolments"}
    prog = project["program"]
    gen = c.post("/api/projects/school/generate", json={"program": prog, "target": "python"})
    assert "groupby" in gen.json()["code"]
    run = c.post("/api/projects/school/run", json={"program": prog, "target": "sql"}).json()
    assert run["ok"] and run["tables"][0]["rows"]
    up = c.post("/api/projects/school/data",
                files={"file": ("pets.csv", (FIXTURES / "pets.csv").read_bytes(), "text/csv")})
    assert up.status_code == 200
    cols = {c["name"]: c for c in up.json()["table"]["columns"]}
    assert cols["age"]["type"] == "int" and cols["age"]["empty"] == 2
    pets = b.program(b.from_("pets", b.limit(2))).model_dump()
    run = c.post("/api/projects/school/run", json={"program": pets, "target": "sql"}).json()
    assert len(run["tables"][0]["rows"]) == 2


def test_upload_rejects_non_csv(tmp_path):
    c = client(tmp_path)
    c.get("/api/projects/school")
    r = c.post("/api/projects/school/data", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400


def test_run_maps_error_to_block(tmp_path):
    c = client(tmp_path)
    c.get("/api/projects/school")
    p = b.print_(b.var("best"))
    prog = b.program(b.from_("enrolments", b.limit(2)),
                     b.foreach("row", b.var("out"), p)).model_dump()
    run = c.post("/api/projects/school/run", json={"program": prog, "target": "python"}).json()
    assert not run["ok"]
    assert run["error"]["kind"] == "NameError"
    assert run["error"]["block_id"] == p.id
    assert "best is used before it has a value" in run["error"]["message"]


def test_erd_matches_school_design(tmp_path):
    c = client(tmp_path)
    c.get("/api/projects/school")
    erd = c.get("/api/projects/school/erd").json()
    links = {(link["one"], link["many"], link["column"], link["kind"]) for link in erd["links"]}
    assert links == {("students", "enrolments", "student_id", "1-*"),
                     ("courses", "enrolments", "course_id", "1-*")}
    assert ["courses", "students"] in [sorted(p) for p in erd["unlinked"]]
    enrol = next(t for t in erd["tables"] if t["name"] == "enrolments")
    assert {c["name"] for c in enrol["columns"] if c["fk"]} == {"student_id", "course_id"}
    students = next(t for t in erd["tables"] if t["name"] == "students")
    assert [c["name"] for c in students["columns"] if c["pk"]] == ["student_id"]


def test_parse_endpoint_keeps_ids(tmp_path):
    c = client(tmp_path)
    project = c.get("/api/projects/school").json()
    prog = project["program"]
    sql = c.post("/api/projects/school/generate", json={"program": prog, "target": "sql"}).json()
    edited = sql["code"].replace("LIMIT 5", "LIMIT 2")
    r = c.post("/api/projects/school/parse",
               json={"code": edited, "lang": "sql", "previous": prog}).json()
    assert r["ok"]
    steps = r["program"]["blocks"][0]["stacks"]["steps"]
    assert steps[-1]["fields"]["n"] == 2
    assert steps[-1]["id"] == prog["blocks"][0]["stacks"]["steps"][-1]["id"]


def test_erd_ignores_coincidental_names(tmp_path):
    c = client(tmp_path)
    c.get("/api/projects/school")
    c.post("/api/projects/school/data",
           files={"file": ("pets.csv", (FIXTURES / "pets.csv").read_bytes(), "text/csv")})
    erd = c.get("/api/projects/school/erd").json()
    assert all(link["column"] != "name" for link in erd["links"])
    assert len(erd["links"]) == 2
