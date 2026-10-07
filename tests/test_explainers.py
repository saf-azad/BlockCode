"""The hover animations must tell the truth: run each animation's story (web/src/explainers/
stories.json) through the engine on a tiny table and check the rows it shows."""

import json
from pathlib import Path

import pytest

from blockcode import build as b
from blockcode.engine import run
from blockcode.project_io import ProjectStore

STORIES = json.loads((Path(__file__).parent.parent / "web" / "src" / "explainers" /
                      "stories.json").read_text())


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    store = ProjectStore(tmp_path_factory.mktemp("stories"))
    store.create("tiny", sample=False)
    j = STORIES["join_inner"]
    files = {
        "lefts.csv": "key,l\n" + "\n".join(f"{k},{i}" for i, k in enumerate(j["left"])),
        "rights.csv": "key,r\n" + "\n".join(f"{k},{i}" for i, k in enumerate(j["right"])),
        "rows.csv": "i,key\n" + "\n".join(f"{i},{k}" for i, k in enumerate(STORIES["group"]["keys"])),
        "piles.csv": "pile,x\n" + "\n".join(f"p{p},{k}" for p, h in enumerate(STORIES["having"]["piles"])
                                            for k in range(h)),
        "heights.csv": "col,h\n" + "\n".join(f"c{i},{h}" for i, h in enumerate(STORIES["order"]["heights"])),
    }
    for name, text in files.items():
        store.add_csv("tiny", name, text.encode())
    return store


def rows(store, program, target="sql"):
    result = run(store, store.load("tiny"), program, target)
    assert result.ok, result.error
    return result.tables[-1]


@pytest.mark.parametrize("target", ["sql", "python"])
def test_inner_join_story(tiny, target):
    st = STORIES["join_inner"]
    t = rows(tiny, b.program(b.from_("lefts", b.join("rights", "key"))), target)
    assert t.total_rows == st["rows"]
    assert sorted(r[0] for r in t.rows) == sorted(set(st["left"]) & set(st["right"]))


@pytest.mark.parametrize("target", ["sql", "python"])
def test_left_join_story(tiny, target):
    st = STORIES["join_left"]
    t = rows(tiny, b.program(b.from_("lefts", b.join("rights", "key", how="left"))), target)
    assert t.total_rows == st["rows"]
    empty = [r for r in t.rows if r[t.columns.index("r")] is None]
    assert len(empty) == st["empty_partners"]


def test_where_story(tiny):
    st = STORIES["where"]
    keep = b.inlist(b.col("i"), st["kept"])
    t = rows(tiny, b.program(b.from_("rows", b.where(keep))))
    assert t.total_rows == len(st["kept"]) and STORIES["group"]["keys"].__len__() == st["rows"]


def test_group_story(tiny):
    t = rows(tiny, b.program(b.from_("rows", b.group(["key"], b.agg("count", None, "n")))))
    assert t.total_rows == STORIES["group"]["groups"]


def test_having_story(tiny):
    st = STORIES["having"]
    t = rows(tiny, b.program(b.from_("piles", b.group(["pile"], b.agg("count", None, "n")),
                                     b.having(b.cmp(">=", b.col("n"), b.lit(st["at_least"]))))))
    assert t.total_rows == st["groups_kept"]


def test_order_story(tiny):
    st = STORIES["order"]
    t = rows(tiny, b.program(b.from_("heights", b.order(("h", st["descending"])))))
    assert [r[1] for r in t.rows] == sorted(st["heights"], reverse=st["descending"])


def test_limit_story(tiny):
    st = STORIES["limit"]
    t = rows(tiny, b.program(b.from_("rows", b.limit(st["n"]))))
    assert t.total_rows == st["n"] < st["rows"] <= 9


def test_every_block_has_an_animation():
    scenes = (Path(__file__).parent.parent / "web" / "src" / "explainers" / "scenes.ts").read_text()
    from blockcode.registry import SPECS

    for spec in SPECS.values():
        if spec.family == "expr":
            continue
        assert f"sc.{spec.type} =" in scenes or f"sc.{spec.type}=" in scenes, spec.type
