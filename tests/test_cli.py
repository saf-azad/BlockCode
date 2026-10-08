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
