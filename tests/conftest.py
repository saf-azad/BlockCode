import shutil
from pathlib import Path

import pytest

from blockcode.project_io import ProjectStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def store(tmp_path_factory) -> ProjectStore:
    root = tmp_path_factory.mktemp("projects")
    s = ProjectStore(root)
    s.create("school")
    s.create("pets", sample=False)
    for csv in sorted(FIXTURES.glob("*.csv")):
        s.add_csv("pets", csv.name, csv.read_bytes())
    return s


@pytest.fixture
def fresh_store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "projects")


def copy_fixture(name: str, dest: Path) -> Path:
    shutil.copy(FIXTURES / name, dest / name)
    return dest / name
