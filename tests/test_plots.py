"""Plots: bad settings are caught before running, failures leave no blank pictures, and R draws
plots whichever way they are made (ggplot2 3 or 4, inside loops)."""

import base64
import shutil

import pytest

from blockcode import build as b
from blockcode.codegen import generate
from blockcode.engine import run
from blockcode.validate import validate

needs_r = pytest.mark.skipif(shutil.which("Rscript") is None, reason="R is not installed")


def grouped(*steps):
    return b.from_("enrolments", b.join("courses", "course_id"),
                   b.group(["dept"], b.agg("avg", "grade", "avg_grade"), b.agg("count", None, "n")),
                   *steps)


def problems(store, prog, target="python"):
    tables = {t.name: t for t in store.load("school").tables}
    return [d for d in validate(prog, tables, target) if d.severity == "error"]


@pytest.mark.parametrize("plot, words", [
    (b.plot("hist", "out", "dept"), "A histogram needs numbers, but dept is text"),
    (b.plot("bar", "out", "avg_grade", "dept"), "The y axis needs numbers, but dept is text"),
    (b.plot("scatter", "out", "dept", "n"), "scatter plot's x axis needs numbers"),
    (b.plot("bar", "out", "dept", "grade"), "out has no column called grade any more"),
])
def test_unplottable_columns_are_problems_on_the_block(store, plot, words):
    prog = b.program(grouped(), plot)
    for target in ("python", "r"):
        found = problems(store, prog, target)
        assert [d.block_id for d in found] == [plot.id]
        assert words in found[0].message


def test_a_bar_for_every_row_of_a_big_table_is_a_problem(store):
    plot = b.plot("bar", "out", "course_id", "grade")
    found = problems(store, b.program(b.from_("enrolments"), plot))
    assert found and found[0].block_id == plot.id and "2,310 rows" in found[0].message
    # a few rows (or rows we can't count without running) are fine
    assert not problems(store, b.program(b.from_("enrolments", b.limit(20)), plot))
    assert not problems(store, b.program(
        b.from_("enrolments", b.where(b.cmp(">", b.col("grade"), b.lit(95)))), plot))


def test_rows_without_numbers_say_how_to_get_some(store):
    plot = b.plot("bar", "out", "course_id", "title")
    found = problems(store, b.program(b.from_("courses"), plot))
    assert found and "no number columns" in found[0].message


def test_run_stops_on_a_plot_problem_without_running(store):
    project = store.load("school")
    plot = b.plot("bar", "out", "dept", "avg_grade")
    result = run(store, project, b.program(plot, grouped()), "python")  # plot above its data
    assert result.error.kind == "Problem" and result.error.block_id == plot.id
    assert not result.plots


def test_good_plots_pass_validation(store):
    prog = b.program(grouped(), b.plot("bar", "out", "dept", "avg_grade"),
                     b.plot("hist", "out", "avg_grade"), b.plot("scatter", "out", "n", "avg_grade"),
                     b.plot("line", "out", "dept", "n"))
    assert not problems(store, prog) and not problems(store, prog, "r")


def test_a_plot_that_fails_leaves_no_blank_picture(store):
    project = store.load("school")
    nothing = b.where(b.cmp(">", b.col("grade"), b.lit(1000)))
    prog = b.program(b.from_("enrolments", nothing), b.plot("hist", "out", "grade"),
                     b.plot("bar", "out", "term", "grade"))
    result = run(store, project, prog, "python")
    assert not result.ok
    assert "no rows" in result.error.message
    assert len(result.plots) == 1  # the histogram drawn before the failure, not a blank bar chart


def test_run_result_carries_the_code_the_editor_shows(store):
    project = store.load("school")
    prog = b.program(grouped(), b.plot("bar", "out", "dept", "n"))
    for target in ("python", "r"):
        shown = generate(prog, project.tables, target, **(
            {"title": project.title or project.name} if target == "r" else {})).code
        assert run(store, project, prog, target).code == shown


def test_python_runs_in_the_warm_worker_and_starts_fresh_each_time(store):
    from blockcode.run.py_worker import POOL

    project = store.load("school")
    prog = b.program(b.raw("python", "import pandas as pd\nprint(pd.options.display.max_rows)\n"
                                     "pd.set_option('display.max_rows', 3)"))
    first = run(store, project, prog, "python")
    second = run(store, project, prog, "python")
    assert first.stdout == second.stdout == "60\n"  # nothing carries over between runs
    if not POOL.broken:
        assert POOL.proc is not None and POOL.proc.poll() is None


def test_python_falls_back_to_a_fresh_process(store, monkeypatch):
    from blockcode.run.py_worker import POOL

    monkeypatch.setattr(POOL, "broken", True)
    project = store.load("school")
    result = run(store, project, b.program(grouped(), b.plot("bar", "out", "dept", "n")), "python")
    assert result.ok and len(result.plots) == 1


def test_runaway_printing_is_clipped(store):
    from blockcode.run import MAX_STDOUT

    project = store.load("school")
    result = run(store, project, b.program(b.raw("python", "print('x' * 1_000_000)")), "python")
    assert len(result.stdout) < MAX_STDOUT + 200 and "more characters" in result.stdout


def test_r_prints_plots_inside_loops():
    code = generate(b.program(grouped(), b.repeat("i", b.lit(2), b.plot("bar", "out", "dept", "n"))),
                    [], "r").code
    assert "  print(ggplot(out, aes(x = dept, y = n)) +" in code
    assert "    geom_col())" in code


@needs_r
def test_r_draws_every_plot_including_loops(store):
    project = store.load("school")
    prog = b.program(grouped(), b.plot("bar", "out", "dept", "avg_grade"),
                     b.repeat("i", b.lit(2), b.plot("scatter", "out", "n", "avg_grade")))
    result = run(store, project, prog, "r")
    assert result.ok, result.error
    assert len(result.plots) == 3
    assert all(base64.b64decode(p)[:4] == b"\x89PNG" for p in result.plots)


@needs_r
def test_r_plot_that_fails_leaves_no_blank_picture(store):
    project = store.load("school")
    # a raw R block gets past validation: ggplot fails while drawing
    prog = b.program(grouped(), b.plot("bar", "out", "dept", "n"),
                     b.raw("r", "ggplot(out, aes(x = nope, y = n)) + geom_col()"))
    result = run(store, project, prog, "r")
    assert not result.ok
    assert len(result.plots) == 1
