from pathlib import Path

from typer.testing import CliRunner

from blockcode.cli import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_end_to_end(tmp_path):
    d = str(tmp_path / "projects")
    r = runner.invoke(app, ["new", "school", "-d", d])
    assert r.exit_code == 0, r.output
    assert "enrolments" in r.output
    r = runner.invoke(app, ["import-csv", "school", str(FIXTURES / "pets.csv"), "-d", d])
    assert r.exit_code == 0 and "8 rows" in r.output
    r = runner.invoke(app, ["code", "school", "-t", "sql", "-d", d])
    assert "GROUP BY dept" in r.output
    sql = runner.invoke(app, ["run", "school", "-t", "sql", "-d", d])
    py = runner.invoke(app, ["run", "school", "-t", "python", "-d", d])
    assert sql.exit_code == 0 and py.exit_code == 0, py.output
    assert "Mathematics" in sql.output
    assert sql.output.splitlines()[2].split()[0] == py.output.splitlines()[2].split()[0]
    r = runner.invoke(app, ["validate", "school", "-t", "sql", "-d", d])
    assert r.exit_code == 0 and "No problems" in r.output


def test_cli_unknown_project(tmp_path):
    r = runner.invoke(app, ["run", "nope", "-d", str(tmp_path)])
    assert r.exit_code == 1


def test_cli_missing_and_bad_files_give_messages_not_tracebacks(tmp_path):
    d = str(tmp_path / "projects")
    runner.invoke(app, ["new", "p", "--empty", "-d", d])

    r = runner.invoke(app, ["import-csv", "p", str(tmp_path / "nope.csv"), "-d", d])
    assert r.exit_code == 1 and "Can't read" in r.output and "Traceback" not in r.output

    bad = tmp_path / "bad.json"
    bad.write_text("not json at all")
    r = runner.invoke(app, ["run", "p", "-d", d, "-p", str(bad)])
    assert r.exit_code == 1 and "isn't a BlockCode" in r.output and "Traceback" not in r.output

    r = runner.invoke(app, ["run", "p", "-d", d, "-p", str(tmp_path / "missing.json")])
    assert r.exit_code == 1 and "Can't read" in r.output


def test_cli_export_without_sql_is_explained(tmp_path):
    d = str(tmp_path / "projects")
    runner.invoke(app, ["new", "p", "--empty", "-d", d])
    runner.invoke(app, ["import-csv", "p", str(FIXTURES / "pets.csv"), "-d", d])
    prog = tmp_path / "loop.json"
    # a program with a For each has no SQL version
    prog.write_text('{"blocks":[{"id":"f1","type":"foreach","fields":{"var":"row"},'
                    '"inputs":{"over":{"id":"v","type":"var","fields":{"name":"out"}}},'
                    '"stacks":{"body":[{"id":"p","type":"print","inputs":'
                    '{"arg0":{"id":"l","type":"lit","fields":{"value":1}}}}]}}]}')
    r = runner.invoke(app, ["export", "p", "-t", "sql", "-d", d, "-o", str(tmp_path / "out"),
                            "-p", str(prog)])
    assert r.exit_code == 1 and "no SQL version" in r.output and "Traceback" not in r.output


def test_cli_numbers_are_not_truncated(tmp_path):
    from blockcode.cli import _cell
    assert _cell(3645000.75) == "3645000.75"
    assert _cell(5.0) == "5"
