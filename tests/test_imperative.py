from blockcode import build as b
from blockcode.codegen import generate
from blockcode.engine import run
from blockcode.validate import validate


def loop_program():
    return b.program(
        b.from_("enrolments", b.join("courses", "course_id"),
                b.group(["dept"], b.agg("avg", "grade", "avg_grade")),
                b.order(("avg_grade", True)), b.limit(3)),
        b.setvar("total", b.lit(0)),
        b.foreach("row", b.var("out"),
                  b.print_(b.field("row", "dept"), b.field("row", "avg_grade")),
                  b.changevar("total", b.lit(1))),
        b.if_(b.cmp("=", b.var("total"), b.lit(3)), [b.print_(b.lit("three rows"))],
              [b.print_(b.lit("something else"))]),
    )


def test_python_loop_code_and_run(store):
    project = store.load("school")
    gen = generate(loop_program(), project.tables, "python")
    assert "for row in out.itertuples(index=False):" in gen.code
    assert "    print(row.dept, row.avg_grade)" in gen.code
    assert "    total += 1" in gen.code
    assert "else:" in gen.code
    result = run(store, project, loop_program(), "python")
    assert result.ok, result.error
    lines = result.stdout.splitlines()
    assert lines[0].startswith("Mathematics ")
    assert lines[-1] == "three rows"


def test_r_loop_code(store):
    project = store.load("school")
    code = generate(loop_program(), project.tables, "r").code
    assert "for (i in seq_len(nrow(out))) {" in code
    assert "  row <- out[i, ]" in code
    assert "  print(paste(row$dept, row$avg_grade))" in code
    assert "} else {" in code


def test_repeat_and_while(store):
    project = store.load("school")
    prog = b.program(
        b.setvar("n", b.lit(1)),
        b.while_(b.cmp("<", b.var("n"), b.lit(20)), b.setvar("n", b.math("*", b.var("n"),
                                                                          b.lit(2)))),
        b.repeat("i", b.lit(2), b.print_(b.var("i"), b.var("n"))),
    )
    result = run(store, project, prog, "python")
    assert result.stdout == "0 32\n1 32\n"
    assert "for (i in seq_len(2) - 1) {" in generate(prog, project.tables, "r").code


def test_var_before_set_is_flagged(store):
    project = store.load("school")
    p = b.print_(b.var("best"))
    prog = b.program(b.from_("enrolments", b.limit(1)), b.foreach("row", b.var("out"), p))
    diags = validate(prog, {t.name: t for t in project.tables}, "python")
    assert any(d.block_id == p.id and "best is used before" in d.message for d in diags)
    sql = validate(prog, {t.name: t for t in project.tables}, "sql")
    assert any(d.severity == "sql" for d in sql)


def test_plots_render_pngs(store):
    project = store.load("school")
    prog = b.program(
        b.from_("enrolments", b.join("courses", "course_id"),
                b.group(["dept"], b.agg("avg", "grade", "avg_grade"), b.agg("count", None, "n"))),
        b.plot("bar", "out", "dept", "avg_grade"),
        b.plot("hist", "out", "avg_grade"),
        b.plot("scatter", "out", "n", "avg_grade"),
        b.plot("line", "out", "dept", "avg_grade"),
    )
    result = run(store, project, prog, "python")
    assert result.ok, result.error
    assert len(result.plots) == 4
    import base64
    assert base64.b64decode(result.plots[0])[:4] == b"\x89PNG"
    sql = generate(prog, project.tables, "sql")
    assert sql.ok and "GROUP BY dept" in sql.code
    assert any(d.severity == "info" and "detached" in d.message for d in sql.diagnostics)
    r = generate(prog, project.tables, "r").code
    assert "ggplot(out, aes(x = dept, y = avg_grade)) +" in r
    assert "#| fig-cap:" in r


def test_traceback_maps_to_block_inside_loop(store):
    project = store.load("school")
    bad = b.print_(b.math("/", b.lit(1), b.lit(0)))
    prog = b.program(b.from_("enrolments", b.limit(2)), b.foreach("row", b.var("out"), bad))
    result = run(store, project, prog, "python")
    assert not result.ok
    assert result.error.kind == "ZeroDivisionError"
    assert result.error.block_id == bad.id


def test_raw_code_runs_as_written(store):
    project = store.load("school")
    prog = b.program(b.raw("python", "x = [1, 2, 3]\nprint(sum(x))"))
    result = run(store, project, prog, "python")
    assert result.stdout == "6\n"
    assert not generate(prog, project.tables, "sql").ok


def test_timeout(store, monkeypatch):
    import blockcode.run.python_runner as pr

    project = store.load("school")
    prog = b.program(b.while_(b.lit(True), b.setvar("x", b.lit(1))))
    gen = generate(prog, project.tables, "python")
    result = pr.run_python(gen, store.dir("school"), [], timeout=3)
    assert result.error.kind == "Timeout"


import shutil  # noqa: E402

import pytest  # noqa: E402

needs_r = pytest.mark.skipif(shutil.which("Rscript") is None, reason="R is not installed")


@needs_r
def test_r_loop_and_plot_run(store):
    project = store.load("school")
    prog = loop_program()
    prog.blocks.append(b.plot("bar", "out", "dept", "avg_grade"))
    result = run(store, project, prog, "r")
    assert result.ok, result.error
    assert '[1] "Mathematics' in result.stdout
    assert '[1] "three rows"' in result.stdout
    assert len(result.plots) == 1


@needs_r
def test_r_error_maps_to_block(store):
    project = store.load("school")
    p = b.print_(b.var("best"))
    prog = b.program(b.from_("enrolments", b.limit(2)), b.foreach("row", b.var("out"), p))
    result = run(store, project, prog, "r")
    assert not result.ok
    assert result.error.block_id == p.id, result.error
    assert "best is used before" in result.error.message
