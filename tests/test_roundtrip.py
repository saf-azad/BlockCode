"""Code → blocks → code. Parsing generated code must give back an equivalent program:
regenerating it in *every* language gives the same code as the original program."""

import pytest

from blockcode import build as b
from blockcode.codegen import generate
from blockcode.parse import parse_code
from tests.programs import pets, school

LANGS = ("sql", "python", "r")


def imperative():
    return {
        "loop_print": b.program(
            b.from_("enrolments", b.join("courses", "course_id"),
                    b.group(["dept"], b.agg("avg", "grade", "avg_grade")),
                    b.order(("avg_grade", True)), b.limit(3)),
            b.setvar("total", b.lit(0)),
            b.foreach("row", b.var("out"),
                      b.if_(b.cmp(">", b.field("row", "avg_grade"), b.lit(70)),
                            [b.print_(b.field("row", "dept"), b.lit("is high"))],
                            [b.print_(b.field("row", "dept"))]),
                      b.changevar("total", b.lit(1))),
            b.print_(b.var("total")),
        ),
        "while_repeat": b.program(
            b.setvar("n", b.lit(1)),
            b.while_(b.and_(b.cmp("<", b.var("n"), b.lit(100)), b.not_(b.cmp("=", b.var("n"), b.lit(64)))),
                     b.setvar("n", b.math("*", b.var("n"), b.lit(2)))),
            b.repeat("i", b.lit(3), b.print_(b.var("i"), b.math("+", b.var("n"), b.var("i")))),
        ),
        "plots": b.program(
            b.from_("enrolments", b.join("courses", "course_id"),
                    b.group(["dept"], b.agg("avg", "grade", "avg_grade"), b.agg("count", None, "n"))),
            b.plot("bar", "out", "dept", "avg_grade"),
            b.plot("line", "out", "dept", "avg_grade"),
            b.plot("scatter", "out", "n", "avg_grade"),
            b.plot("hist", "out", "avg_grade"),
        ),
    }


DATA = {**{f"school/{k}": v for k, v in school().items()},
        **{f"pets/{k}": v for k, v in pets().items()}}
ALL = {**DATA, **{f"imperative/{k}": v for k, v in imperative().items()}}


def tables_for(store, key):
    project = store.load("pets" if key.startswith("pets/") else "school")
    return {t.name: t for t in project.tables}


def assert_same_code(p1, p2, tables, langs=LANGS):
    for lang in langs:
        assert generate(p2, tables, lang).code == generate(p1, tables, lang).code, lang


@pytest.mark.parametrize("key", list(DATA))
def test_sql_round_trip(store, key):
    tables = tables_for(store, key)
    program = DATA[key]
    code = generate(program, tables, "sql").code
    result = parse_code(code, "sql", tables)
    assert result.ok, result.diagnostics
    assert_same_code(program, result.program, tables)


@pytest.mark.parametrize("lang", ["python", "r"])
@pytest.mark.parametrize("key", list(ALL))
def test_round_trip(store, key, lang):
    tables = tables_for(store, key)
    program = ALL[key]
    code = generate(program, tables, lang).code
    result = parse_code(code, lang, tables)
    assert result.ok, result.diagnostics
    assert not [d for d in result.diagnostics if d.severity != "info"], result.diagnostics
    assert not any(blk.type == "raw" for blk in result.program.walk()), \
        generate(result.program, tables, lang).code
    langs = LANGS if not key.startswith("imperative/") else ("python", "r")
    assert_same_code(program, result.program, tables, langs)


@pytest.mark.parametrize("lang", LANGS)
def test_ids_are_kept(store, lang):
    tables = tables_for(store, "school/x")
    program = school()["department_grades"]
    code = generate(program, tables, lang).code.replace("5", "3")
    result = parse_code(code, lang, tables, previous=program)
    old_ids = [x.id for x in program.walk()]
    new_ids = [x.id for x in result.program.walk()]
    assert new_ids == old_ids
    lim = [x for x in result.program.walk() if x.type == "limit"][0]
    assert lim.field("n") == 3
    # spans point at the line that holds the limit
    gen = generate(result.program, tables, lang)
    assert result.spans[lim.id] == gen.lines_for(lim.id)
