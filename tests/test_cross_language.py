"""The core promise: the same blocks give the same table in SQL, pandas and R. These cases
were found by exploratory testing to diverge, and are kept here so they stay in step."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from blockcode import build as b
from blockcode.codegen import generate
from blockcode.data_io import add_table
from blockcode.engine import run_in
from blockcode.parse import parse_code
from blockcode.run.r_runner import rscript

TARGETS = ["sql", "python"] + (["r"] if rscript() else [])


def workspace(tmp_path, name, csv: bytes):
    db = tmp_path / "db.sqlite"
    sqlite3.connect(db).close()
    info, _ = add_table(tmp_path, db, f"{name}.csv", csv, name=name)
    return tmp_path, db, [info]


def results(tmp_path, tables, prog):
    """Each target's result rows as a set of tuples (order-insensitive), or raise on error."""
    db = tmp_path / "db.sqlite"
    out = {}
    for t in TARGETS:
        r = run_in(tmp_path, db, tables, prog, t)
        assert r.ok, f"{t}: {r.error.message if r.error else '?'}"
        tbl = r.tables[-1]
        out[t] = (tbl.columns, sorted(tuple(row) for row in tbl.rows))
    return out


def same(res) -> bool:
    vals = list(res.values())
    return all(v[1] == vals[0][1] for v in vals)


def ordered(tmp_path, tables, prog):
    db = tmp_path / "db.sqlite"
    out = {}
    for t in TARGETS:
        r = run_in(tmp_path, db, tables, prog, t)
        assert r.ok, f"{t}: {r.error.message if r.error else '?'}"
        out[t] = [tuple(row) for row in r.tables[-1].rows]
    return out


@pytest.fixture
def nums(tmp_path):
    return workspace(tmp_path, "nums", b"name,age,price\nA,-7,2.5\nB,8,7.0\nC,5,3.0\nD,,1.5\n")


def test_modulo_matches(nums):
    d, db, tables = nums
    for col in ("age", "price"):
        prog = b.program(b.from_("nums", b.derive("m", b.math("%", b.col(col), b.lit(3)))))
        res = results(d, tables, prog)
        assert same(res), (col, res)


def test_integer_modulo_stays_integer(nums):
    d, db, tables = nums
    prog = b.program(b.from_("nums", b.derive("m", b.math("%", b.col("age"), b.lit(3)))))
    r = run_in(d, db, tables, prog, "sql")
    vals = [row[-1] for row in r.tables[0].rows if row[-1] is not None]
    assert all(isinstance(v, int) for v in vals), vals


def test_text_comparison_and_minmax_match(tmp_path):
    d, db, tables = workspace(tmp_path, "t", b"name\nAlice\nbob\nZed\nEve\nal\n")
    res = results(d, tables, b.program(b.from_("t", b.where(b.cmp(">", b.col("name"), b.lit("M"))))))
    assert same(res), res
    g = b.program(b.from_("t", b.derive("k", b.lit(1)),
                          b.group(["k"], b.agg("min", "name", "lo"), b.agg("max", "name", "hi"))))
    assert same(results(d, tables, g))


def test_sort_ties_same_order(tmp_path):
    rows = "".join(f"r{i},{i % 3}\n" for i in range(30))
    d, db, tables = workspace(tmp_path, "t", b"id,g\n" + rows.encode())
    prog = b.program(b.from_("t", b.order("g"), b.limit(8)))
    out = ordered(d, tables, prog)
    first = list(out.values())[0]
    assert all(v == first for v in out.values()), out


def test_like_special_characters_match(tmp_path):
    d, db, tables = workspace(tmp_path, "t",
                              "label\n50% off\nSKU_1\nSKU_2\nplain\nhalf%\n".encode())
    for op, val in [("contains", "50%"), ("contains", "_"), ("starts", "SKU_"), ("ends", "%")]:
        prog = b.program(b.from_("t", b.where(b.text(op, b.col("label"), val))))
        res = results(d, tables, prog)
        assert same(res), (op, val, res)


def test_having_division_matches(tmp_path):
    d, db, tables = workspace(tmp_path, "t",
                              b"dept,v\nA,1\nA,1\nA,1\nB,1\nB,1\nC,1\n")
    prog = b.program(b.from_("t", b.group(["dept"], b.agg("count", None, "n")),
                              b.having(b.cmp(">", b.math("/", b.col("n"), b.lit(2)), b.lit(1)))))
    res = results(d, tables, prog)
    assert same(res) and len(res["sql"][1]) == 1, res  # only A (3/2=1.5>1)


def test_r_keeps_text_columns_as_text(tmp_path):
    # readr would read "1,5" and "14:30" as a number and a time; col_types keeps them text
    if "r" not in TARGETS:
        pytest.skip("R isn't installed")
    d, db, tables = workspace(tmp_path, "t",
                              'code,when\n"1,5",14:30\n"2,25",09:05\n'.encode())
    assert tables[0].column("code").type == "text"
    prog = b.program(b.from_("t", b.where(b.cmp("=", b.col("code"), b.lit("1,5")))))
    res = results(d, tables, prog)
    assert same(res) and len(res["sql"][1]) == 1, res


def test_full_width_column_name_runs_in_python(tmp_path):
    # a full-width-digit aggregate alias must not be rewritten to ASCII by Python's NFKC
    d, db, tables = workspace(tmp_path, "shop", "store,Ｎｏ\nTokyo,10\nOsaka,20\nTokyo,30\n".encode())
    prog = b.program(b.from_("shop", b.group(["store"], b.agg("avg", "Ｎｏ", "avg_Ｎｏ"))))
    res = results(d, tables, prog)
    assert same(res) and "avg_Ｎｏ" in res["python"][0], res


def test_not_like_keeps_its_meaning(tmp_path):
    d, db, tables = workspace(tmp_path, "t", b"name\namy\nbob\nann\nzed\n")
    typed = "SELECT name FROM t WHERE name NOT LIKE 'a%'"
    prog = parse_code(typed, "sql", tables).program
    assert prog is not None
    res = results(d, tables, prog)
    assert same(res) and set(res["sql"][1]) == {("bob",), ("zed",)}, res


def test_huge_cell_and_lone_cr_do_not_crash(tmp_path):
    db = tmp_path / "db.sqlite"
    sqlite3.connect(db).close()
    big = b"a,b\n" + b"x" * 200_000 + b",1\n"
    info, _ = add_table(tmp_path, db, "big.csv", big, name="big")
    assert info.rows == 1
    cr = b"city,n\rParis,1\rLyon,2\r"
    info2, _ = add_table(tmp_path, db, "cr.csv", cr, name="cr")
    assert info2.rows == 2 and [c.name for c in info2.columns] == ["city", "n"]
