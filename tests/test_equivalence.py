"""The main safety net: SQL and pandas give the same table for every data example."""

import math

import pytest

from blockcode.engine import run
from tests.programs import pets, school


def norm(v):
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v):
            return None
        return round(v, 6)
    return v


def rows_of(result):
    assert result.ok, result.error
    t = result.tables[-1]
    return t.columns, [tuple(norm(v) for v in r) for r in t.rows]


def has_order(program):
    return any(b.type == "order" for b in program.walk())


def compare(store, project_name, program):
    project = store.load(project_name)
    sql = run(store, project, program, "sql")
    if sql.ok and sql.tables and sql.tables[-1].total_rows > len(sql.tables[-1].rows) \
            and not has_order(program):
        # Only the first rows come back; fix the order so both sides return the same ones.
        from blockcode import build as b

        program = program.model_copy(deep=True)
        steps = program.blocks[-1].stacks["steps"]
        steps.append(b.order(*[(c, False) for c in sql.tables[-1].columns]))
        sql = run(store, project, program, "sql")
    sql_cols, sql_rows = rows_of(sql)
    py_cols, py_rows = rows_of(run(store, project, program, "python"))
    assert sql_cols == py_cols
    if has_order(program):
        assert sql_rows == py_rows
    else:
        key = lambda r: tuple((x is None, str(type(x)), x if x is not None else 0) for x in r)  # noqa: E731
        assert sorted(sql_rows, key=key) == sorted(py_rows, key=key)
    return sql_rows


@pytest.mark.parametrize("name", list(school()))
def test_school_examples_match(store, name):
    rows = compare(store, "school", school()[name])
    assert rows, "example should return rows"


@pytest.mark.parametrize("name", list(pets()))
def test_null_semantics_match(store, name):
    compare(store, "pets", pets()[name])


def test_null_rules_are_sql_rules(store):
    project = store.load("pets")
    # != skips the empty species? species has no empties, but NOT age > 3 must skip empty ages
    _, rows = rows_of(run(store, project, pets()["not_skips_empty"], "python"))
    ages = [r[3] for r in rows]
    assert None not in ages
    _, rows = rows_of(run(store, project, pets()["sort_with_empty"], "python"))
    assert [r[3] for r in rows][-2:] == [None, None]


needs_r = pytest.mark.skipif(__import__("shutil").which("Rscript") is None,
                             reason="R is not installed")


@needs_r
@pytest.mark.parametrize("name", list(school()))
def test_r_matches_sql(store, name):
    project = store.load("school")
    program = school()[name]
    _, sql_rows = rows_of(run(store, project, program, "sql"))
    _, r_rows = rows_of(run(store, project, program, "r"))
    if has_order(program):
        assert sql_rows == r_rows
    else:
        key = lambda r: tuple((x is None, str(x)) for x in r)  # noqa: E731
        assert sorted(sql_rows, key=key) == sorted(r_rows, key=key)


def test_r_without_rscript_explains(store, monkeypatch):
    import blockcode.run.r_runner as rr

    monkeypatch.setattr(rr, "rscript", lambda: None)
    project = store.load("school")
    result = run(store, project, school()["year_counts"], "r")
    assert not result.ok and result.error.kind == "NoR"


@needs_r
@pytest.mark.parametrize("name", list(pets()))
def test_r_null_semantics_match_sql(store, name):
    project = store.load("pets")
    program = pets()[name]
    sql_cols, sql_rows = rows_of(run(store, project, program, "sql"))
    r_cols, r_rows = rows_of(run(store, project, program, "r"))
    assert sql_cols == r_cols
    if has_order(program):
        assert sql_rows == r_rows
    else:
        key = lambda r: tuple((x is None, str(x)) for x in r)  # noqa: E731
        assert sorted(sql_rows, key=key) == sorted(r_rows, key=key)
