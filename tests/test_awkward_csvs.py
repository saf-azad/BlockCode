"""Real-world CSVs are messy. Each one is tidied on upload so SQL, pandas and R read the same
table, and every block runs the same in all three."""

import math

import pytest

from blockcode import build as b
from blockcode.codegen import generate
from blockcode.data_io import CsvError, normalize_csv, table_name_for
from blockcode.engine import run
from blockcode.parse import parse_code
from blockcode.project_io import ProjectStore
from blockcode.run.r_runner import rscript

CSVS = {
    "weird_names.csv": "First Name,order,select,2024 sales,price ($),e-mail,Group\n"
                       "Ana,1,yes,1200,9.99,a@x.io,A\nBo,2,no,,19.5,b@x.io,B\n"
                       "Cy,3,yes,800,,c@x.io,A\nDee,4,no,1500,4.25,,B\n",
    "semicolon.csv": "city;country;population;share\nParis;France;2148000;1,5\n"
                     "Lyon;France;513000;0,25\nBerlin;Germany;3645000;2\n",
    "tabs.tsv": "name\tage\tcity\nAna\t30\tParis\nBo\t25\tLyon\n",
    "bom.csv": "﻿id,name,score\n1,Ana,90\n2,Bo,75\n3,Cy,88\n",
    "crlf.csv": "id,name,score\r\n1,Ana,90\r\n2,Bo,75\r\n",
    "quoted.csv": 'id,comment,amount\n1,"Hello, world",10\n2,"She said ""hi""",20\n'
                  '3,"multi\nline",30\n',
    "headers_only.csv": "a,b,c\n",
    "dupes.csv": "a,a,B,b\n1,2,3,4\n5,6,7,8\n",
    "blank_header.csv": ",name,value\n0,x,1\n1,y,2\n",
    "bools.csv": "name,active\nA,true\nB,false\nC,TRUE\n",
    "mixed.csv": 'code,amount,pct,zip\nA12,"1,234",12%,02139\n42,500,5%,10001\n007,"2,000",50%,00501\n',
    "nulls.csv": "name,value,note\nA,1,NA\nB,,N/A\nC,3,null\nD,NA,\n",
    "spaces.csv": " id , name , score \n 1 , Ana , 90 \n 2 , Bo , 75 \n",
    "ragged.csv": "a,b,c\n1,2,3\n4,5,6,7\n8,9\n",
    "unicode.csv": "名前,größe,emoji\n太郎,1.75,😀\nZoë,1.62,🎉\n",
    "class.csv": "id,for,in\n1,2,3\n",
}
LATIN1 = "ville,pays,note\nCafé,Zürich,3\nNaïve,Genève,5\n".encode("latin-1")


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    store = ProjectStore(tmp_path_factory.mktemp("awkward"))
    store.create("p", sample=False)
    for name, text in CSVS.items():
        store.add_csv("p", name, text.encode("utf-8"))
    store.add_csv("p", "latin1.csv", LATIN1)
    return store


def norm(rows):
    def f(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, float):
            return int(v) if v.is_integer() else round(v, 6)
        return v
    return sorted((tuple(f(v) for v in r) for r in rows), key=repr)


def programs(t):
    # (a column that is entirely empty sums to empty in SQL but 0 in pandas and R; see
    # "Known limits" in docs/PLAN.md)
    num = [c.name for c in t.columns if c.type in ("int", "float") and c.empty < t.rows]
    txt = [c.name for c in t.columns if c.type == "text"]
    out = {"limit": b.program(b.from_(t.name, b.limit(3))),
           "select": b.program(b.from_(t.name, b.select(*[c.name for c in t.columns][:3]),
                                       b.order(t.columns[0].name)))}
    if num:
        out["where"] = b.program(b.from_(t.name, b.where(b.cmp(">", b.col(num[0]), b.lit(1)))))
        out["derive"] = b.program(b.from_(t.name, b.derive("doubled", b.math("*", b.col(num[-1]),
                                                                              b.lit(2)))))
        out["total"] = b.program(b.from_(t.name, b.group([], b.agg("sum", num[-1], "total"),
                                                          b.agg("count", None, "n"))))
    if txt:
        aggs = [b.agg("count", None, "n")] + ([b.agg("avg", num[0], "mean")] if num else [])
        out["group"] = b.program(b.from_(t.name, b.group([txt[0]], *aggs)))
        out["filled"] = b.program(b.from_(t.name, b.where(b.not_(b.isempty(b.col(txt[0]))))))
        out["contains"] = b.program(b.from_(t.name, b.where(b.text("contains", b.col(txt[0]), "a"))))
    return out


def cases():
    names = [table_name_for(n) for n in CSVS] + ["latin1"]
    return [(n, p) for n in names for p in ("limit", "select", "where", "derive", "total", "group",
                                            "filled", "contains")]


@pytest.mark.parametrize("table,prog", cases())
def test_every_language_reads_the_same_table(project, table, prog):
    p = project.load("p")
    info = p.table(table)
    progs = programs(info)
    if prog not in progs:
        pytest.skip("no column of that kind")
    program = progs[prog]
    targets = ["sql", "python"] + (["r"] if rscript() else [])
    results = {}
    for target in targets:
        r = run(project, p, program, target)
        assert r.ok, f"{target}: {r.error}"
        results[target] = r.tables[-1]
        # and the generated code reads back as the same blocks
        code = generate(program, {t.name: t for t in p.tables}, target).code
        back = parse_code(code, target, p.tables, previous=program)
        assert back.ok and not [d for d in back.diagnostics if d.severity == "info"], target
    first = results["sql"]
    for target, t in results.items():
        assert t.total_rows == first.total_rows, target
        assert norm(t.rows) == norm(first.rows), target


def test_tidy_headers_and_values(project):
    p = project.load("p")
    cols = lambda n: [(c.name, c.type) for c in p.table(n).columns]  # noqa: E731
    assert cols("semicolon") == [("city", "text"), ("country", "text"), ("population", "int"),
                                 ("share", "float")]
    assert cols("tabs") == [("name", "text"), ("age", "int"), ("city", "text")]
    assert [c for c, _ in cols("dupes")] == ["a", "a_2", "B", "b_2"]
    assert [c for c, _ in cols("blank_header")] == ["column_1", "name", "value"]
    assert [c for c, _ in cols("spaces")] == ["id", "name", "score"]
    assert [c for c, _ in cols("ragged")] == ["a", "b", "c", "column_4"]
    assert dict(cols("mixed"))["amount"] == "int"
    assert dict(cols("mixed"))["code"] == "text"
    assert p.table("nulls").column("note").empty == 4
    assert p.table("class_data") is not None  # "class" can't be a Python variable
    assert p.table("headers_only").rows == 0


@pytest.mark.parametrize("content,message", [
    (b"", "empty"), (b"   \n\n", "empty"), (b"PK\x03\x04xl/workbook", "Excel"),
    (bytes(range(256)) * 8, "doesn't look like a CSV"),
])
def test_unreadable_files_get_a_plain_reason(content, message):
    with pytest.raises(CsvError, match=message):
        normalize_csv(content)


def test_notes_say_what_was_tidied():
    notes = normalize_csv("a;b\n1,5;NA\n2;x\n".encode("cp1252") + "é;é\n".encode("cp1252")).notes
    text = " ".join(notes)
    assert "Windows-1252" in text and "semicolons" in text and "empty" in text


def test_names_that_are_not_python_identifiers(project):
    p = project.load("p")
    program = b.program(b.from_("weird_names",
                                b.derive("for", b.math("*", b.col("order"), b.lit(2))),
                                b.group(["Group"], b.agg("sum", "for", "2nd"),
                                        b.agg("count", None, "class")),
                                b.order("Group")))
    tables = {t.name: t for t in p.tables}
    rows = None
    for target in ["sql", "python"] + (["r"] if rscript() else []):
        r = run(project, p, program, target)
        assert r.ok, f"{target}: {r.error}"
        assert r.tables[-1].columns == ["Group", "2nd", "class"]
        assert rows is None or norm(r.tables[-1].rows) == rows
        rows = norm(r.tables[-1].rows)
        back = parse_code(generate(program, tables, target).code, target, p.tables, previous=program)
        assert back.ok and not [d for d in back.diagnostics if d.severity == "info"], target
    assert rows == [("A", 8, 2), ("B", 12, 2)]
