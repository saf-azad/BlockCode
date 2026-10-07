"""Golden codegen tests: generated code for every example and target is checked in.

Regenerate with:  UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py
"""

import os
from pathlib import Path

import pytest

from blockcode.codegen import generate
from blockcode.examples import school

GOLDEN = Path(__file__).parent / "golden"
EXT = {"sql": "sql", "python": "py", "r": "R"}


@pytest.mark.parametrize("target", ["sql", "python", "r"])
@pytest.mark.parametrize("name", list(school()))
def test_golden(store, name, target):
    project = store.load("school")
    code = generate(school()[name], project.tables, target).code
    path = GOLDEN / f"{name}.{EXT[target]}"
    if os.environ.get("UPDATE_GOLDEN") or not path.exists():
        path.write_text(code)
    assert code == path.read_text()
