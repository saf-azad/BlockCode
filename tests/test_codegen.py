from blockcode import build as b
from blockcode.codegen import generate
from blockcode.codegen.expr import PandasRenderer, RRenderer, SqlRenderer


def test_source_map_tags_every_clause(store):
    project = store.load("school")
    where = b.where(b.cmp(">", b.col("grade"), b.lit(50)))
    lim = b.limit(3)
    prog = b.program(b.from_("enrolments", where, lim))
    for target in ("sql", "python", "r"):
        gen = generate(prog, project.tables, target)
        assert gen.lines_for(where.id), target
        assert gen.lines_for(lim.id), target
        for n in gen.lines_for(where.id):
            assert "50" in gen.lines[n - 1].text


def test_precedence_brackets():
    e = b.and_(b.or_(b.cmp("=", b.col("a"), b.lit(1)), b.cmp("=", b.col("b"), b.lit(2))),
               b.not_(b.isempty(b.col("c"))))
    assert SqlRenderer()(e) == "(a = 1 OR b = 2) AND NOT (c IS NULL)"
    assert PandasRenderer("df")(e) == \
        '((df["a"] == 1) | (df["b"] == 2)) & ~df["c"].isna()'
    assert RRenderer()(e) == "(a == 1 | b == 2) & !is.na(c)"


def test_maths_precedence():
    e = b.math("*", b.math("+", b.col("a"), b.lit(1)), b.math("-", b.col("b"), b.lit(2)))
    assert SqlRenderer()(e) == "(a + 1) * (b - 2)"
    e2 = b.math("-", b.col("a"), b.math("-", b.col("b"), b.col("c")))
    assert SqlRenderer()(e2) == "a - (b - c)"


def test_sql_quotes_awkward_names():
    e = b.cmp("=", b.col("first name"), b.lit("O'Neil"))
    assert SqlRenderer()(e) == "\"first name\" = 'O''Neil'"
    assert RRenderer()(e) == '`first name` == "O\'Neil"'


def test_sql_whole_number_division():
    r = SqlRenderer(types={"a": "int", "b": "int"})
    assert r(b.math("/", b.col("a"), b.lit(2))) == "a / 2.0"
    assert r(b.math("/", b.col("a"), b.col("b"))) == "CAST(a AS REAL) / b"


def test_python_only_program_turns_sql_off(store):
    project = store.load("school")
    prog = b.program(
        b.from_("enrolments", b.limit(3)),
        b.foreach("row", b.var("out"), b.print_(b.field("row", "grade"))),
    )
    gen = generate(prog, project.tables, "sql")
    assert not gen.ok
    assert any(d.severity == "sql" and "for each" in d.message for d in gen.diagnostics)
    assert any(d.severity == "sql" and "print" in d.message for d in gen.diagnostics)


def test_plan_diagnostics(store):
    project = store.load("school")
    hav = b.having(b.cmp(">", b.col("n"), b.lit(1)))
    bad = b.where(b.cmp(">", b.col("nope"), b.lit(1)))
    prog = b.program(b.from_("enrolments", bad, hav))
    msgs = {d.message for d in generate(prog, project.tables, "sql").diagnostics}
    assert "HAVING needs a Group by block above it." in msgs
    assert '"nope" is not a column here.' in msgs
