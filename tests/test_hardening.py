"""Block fields are data, never code: every value from a block reaches the generated code as a
quoted literal or a checked identifier, and a program that breaks that is refused, not run."""

import ast
import re
import sqlite3
import time

import pytest

from blockcode import build as b
from blockcode.codegen import generate
from blockcode.codegen.expr import py_str
from blockcode.data_io import add_table
from blockcode.engine import run_in
from blockcode.ir import Block, Program
from blockcode.run.sql_runner import run_sql
from blockcode.validate import validate

PETS = b"pet_id,name,species,age\n1,Rex,dog,3\n2,Tom,cat,5\n3,Bo,dog,1\n"
# names that aren't plain identifiers: they must never be written into Python as code
BAD_NAMES = ["two words", "line\nbreak", "for", "1st", "a-b", "x;y", "pd", ""]


@pytest.fixture
def ws(tmp_path):
    db = tmp_path / "db.sqlite"
    sqlite3.connect(db).close()
    info, _ = add_table(tmp_path, db, "pets.csv", PETS, name="pets")
    return tmp_path, db, [info]


def code_lines(code: str) -> list[str]:
    """The lines of generated Python or R that aren't comments."""
    return [ln for ln in code.splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "..."))]


def outside_strings(line: str) -> str:
    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)


def bad_name_programs(name: str) -> dict[str, Program]:
    return {
        "setvar": b.program(b.setvar(name, b.lit(1))),
        "changevar": b.program(b.setvar("n", b.lit(1)), b.changevar(name, b.lit(1))),
        "foreach var": b.program(b.from_("pets"), b.foreach(name, b.var("out"), b.print_(b.lit(1)))),
        "foreach over": b.program(b.from_("pets"), b.foreach("row", b.var(name), b.print_(b.lit(1)))),
        "repeat var": b.program(b.repeat(name, b.lit(2), b.print_(b.lit(1)))),
        "var": b.program(b.print_(b.var(name))),
        "field var": b.program(b.from_("pets"), b.foreach("row", b.var("out"), b.print_(b.field(name, "age")))),
        "result name": b.program(b.from_("pets", name=name)),
        "table": b.program(b.from_(name)),
        "join table": b.program(b.from_("pets", b.join(name, "pet_id"))),
        "plot data": b.program(b.from_("pets"), b.plot("bar", name, "name", "age")),
    }


@pytest.mark.parametrize("name", [n for n in BAD_NAMES if n])
def test_bad_names_never_reach_python_as_code(name, ws):
    d, db, tables = ws
    for where, prog in bad_name_programs(name).items():
        gen = generate(prog, tables, "python")
        assert any(x.severity == "error" for x in gen.diagnostics), where
        if name not in ("for", "pd"):  # words the generated code uses anyway
            for line in code_lines(gen.code):
                assert name not in outside_strings(line), (where, line)
        result = run_in(d, db, tables, prog, "python")
        assert not result.ok and result.error.kind == "Problem", where


def test_comment_lines_stay_comments():
    # an error message that quotes a block's settings must not spill onto a new line of code
    odd = Block(id="e1", type="cmp", fields={"op": "nope\nMARKER = 1"},
                inputs={"a": b.col("age"), "b": b.lit(1)})
    prog = b.program(b.from_("pets"), b.if_(odd, [b.print_(b.lit(1))]))
    for target in ("python", "r"):
        code = generate(prog, {}, target).code
        assert all("MARKER" not in ln for ln in code_lines(code)), (target, code)


def test_limit_and_bins_are_whole_numbers_or_left_out():
    for n in ["3; x", "abc", -1, 2.5, True, None]:
        prog = b.program(b.from_("pets", b.limit(n)))
        for target in ("sql", "python", "r"):
            gen = generate(prog, {}, target)
            assert "LIMIT needs a whole number of rows." in {x.message for x in gen.diagnostics}
            assert str(n) not in gen.code.replace("pets", ""), (target, n, gen.code)
    plot = b.block("plot", {"chart": "hist", "data": "out", "x": "age", "bins": "many"})
    gen = generate(b.program(b.from_("pets"), plot), {}, "python")
    assert any(x.severity == "error" for x in gen.diagnostics) and "many" not in gen.code


def test_unknown_summaries_and_operators_are_problems_not_code():
    prog = b.program(b.from_("pets", b.group(["species"], b.agg("median_of", "age", "m"))))
    for target in ("sql", "python", "r"):
        gen = generate(prog, {}, target)
        assert any("is not a summary I know" in x.message for x in gen.diagnostics)
        assert all("median_of" not in ln for ln in code_lines(gen.code) if "agg(" not in ln), target
    logic = Block(id="l1", type="logic", fields={"op": "xor"}, inputs={"a": b.lit(1), "b": b.lit(2)})
    for target in ("sql", "python", "r"):
        gen = generate(b.program(b.from_("pets", b.where(logic))), {}, target)
        assert any('Pick "and" or "or".' in x.message for x in gen.diagnostics), target


@pytest.mark.parametrize("fields", [
    {"table": ["pets"]}, {"table": {"x": 1}}, {"name": 5},
])
def test_settings_of_the_wrong_kind_are_refused(fields, ws):
    d, db, tables = ws
    prog = Program(blocks=[Block(id="f1", type="from", fields=fields)])
    for target in ("sql", "python", "r"):
        gen = generate(prog, tables, target)
        assert gen.code == "" and gen.diagnostics[0].severity == "error"
        assert not run_in(d, db, tables, prog, target).ok


def test_malformed_blocks_are_problems_not_crashes():
    progs = [
        Program(blocks=[Block(id="x", type="no_such_block")]),
        b.program(b.from_("pets", b.block("group", {"by": ["species"], "aggs": [{"func": "count"}]}))),
        b.program(b.from_("pets", b.block("order", {"keys": [{"desc": True}]}))),
        b.program(b.block("print", inputs={"argX": b.lit(1)})),
        b.program(b.from_("pets", b.block("inlist", {"values": [[1]]}))),
    ]
    for prog in progs:
        for target in ("sql", "python", "r"):
            gen = generate(prog, {}, target)
            validate(prog, {}, target, generated=gen)  # no exception


def test_too_many_blocks_or_too_deep_is_refused():
    deep = b.lit(1)
    for _ in range(400):
        deep = b.not_(deep)
    gen = generate(b.program(b.from_("pets", b.where(deep))), {}, "python")
    assert gen.code == "" and "nested too deeply" in gen.diagnostics[0].message
    many = b.program(*[b.setvar("x", b.lit(i)) for i in range(2500)])
    assert "too many" in generate(many, {}, "python").diagnostics[0].message


def test_strings_never_span_lines():
    for s in ["a\rb", "a b", "tab\there", "nul\x00", 'quote " and \\ slash', "é ü 中文"]:
        lit = py_str(s)
        assert "\n" not in lit and "\r" not in lit and " " not in lit
        assert ast.literal_eval(lit) == s


def test_sql_runs_are_time_limited(ws):
    d, db, tables = ws
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE big (k INTEGER)")
    con.executemany("INSERT INTO big VALUES (?)", [(1,)] * 3000)
    con.commit()
    con.close()
    from blockcode.ir import ColumnInfo, TableInfo

    big = TableInfo(name="big", file="data/big.csv", rows=3000, columns=[ColumnInfo(name="k", type="int")])
    prog = b.program(b.from_("big", b.join("big", "k"), b.join("big", "k")))
    gen = generate(prog, [big], "sql")
    start = time.monotonic()
    result = run_sql(gen, db, ["out"], timeout=0.5)
    assert time.monotonic() - start < 5
    assert not result.ok and result.error.kind == "Timeout"
    assert "took too long" in result.error.message


def test_sql_counts_rows_it_does_not_return(ws):
    d, db, tables = ws
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE many (k INTEGER)")
    con.executemany("INSERT INTO many VALUES (?)", [(i,) for i in range(1000)])
    con.commit()
    con.close()
    from blockcode.ir import ColumnInfo, TableInfo

    many = TableInfo(name="many", file="data/many.csv", rows=1000, columns=[ColumnInfo(name="k", type="int")])
    result = run_sql(generate(b.program(b.from_("many")), [many], "sql"), db, ["out"])
    assert result.ok and result.tables[0].total_rows == 1000 and len(result.tables[0].rows) == 200


AWKWARD = ["two words", "back\\slash", "tick`", "back\\`tick", "line\nbreak", "100%", "é ü", "a\"b"]


@pytest.mark.parametrize("name", AWKWARD)
def test_r_quotes_any_column_name_exactly(name, tmp_path):
    from blockcode.codegen.expr import r_ident
    from blockcode.run.r_runner import rscript

    if rscript() is None:
        pytest.skip("R isn't installed")
    import subprocess

    script = tmp_path / "q.R"
    # one statement that makes a column with this name, then a check that R kept it exactly
    script.write_text(f"x <- data.frame(k = 1) |> transform({r_ident(name)} = 2, check.names = FALSE)\n"
                      f"cat(identical(names(x)[2], {py_str(name)}), length(parse('{script}')))\n",
                      encoding="utf-8")
    out = subprocess.run([rscript(), "--vanilla", str(script)], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "TRUE 2", (name, out.stdout, out.stderr)


@pytest.mark.parametrize("name", [n for n in BAD_NAMES if n and n not in ("pd", "1st", "for")] + ["if", "a\\`b"])
def test_bad_names_never_reach_r_as_code(name, ws):
    d, db, tables = ws
    for where, prog in bad_name_programs(name).items():
        gen = generate(prog, tables, "r")
        assert any(x.severity == "error" for x in gen.diagnostics), where
        assert not run_in(d, db, tables, prog, "r").ok, where


def test_long_and_odd_file_names_make_short_table_names(tmp_path):
    from blockcode.data_io import table_name_for

    assert len(table_name_for("x" * 300 + ".csv")) <= 60
    db = tmp_path / "db.sqlite"
    sqlite3.connect(db).close()
    info, _ = add_table(tmp_path, db, "y" * 300 + ".csv", PETS)
    assert info.name == "y" * 60
    headers = add_table(tmp_path, db, "odd.csv", b"a\x01b,c\x7fd\n1,2\n")[0].columns
    assert [c.name for c in headers] == ["ab", "cd"]
