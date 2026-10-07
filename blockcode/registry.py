"""Block specs: what each block is called in each language and which targets it supports.

The editor builds its palette from ``GET /api/blocks``; validation uses ``targets`` to
explain where SQL ends.
"""

from __future__ import annotations

from pydantic import BaseModel

TARGETS = ("sql", "python", "r")


class BlockSpec(BaseModel):
    type: str
    family: str  # "source" | "step" | "expr" | "python" | "plot"
    labels: dict[str, str]  # keyword shown on the block per language
    targets: tuple[str, ...] = TARGETS
    caption: str = ""  # what the block does to the rows (hover explainer)
    single: bool = False  # at most one per stack

    @property
    def sql_ok(self) -> bool:
        return "sql" in self.targets


def _spec(type, family, sql, py, r, caption="", targets=TARGETS, single=False) -> BlockSpec:
    return BlockSpec(type=type, family=family, labels={"sql": sql, "python": py, "r": r},
                     caption=caption, targets=targets, single=single)


PY_R = ("python", "r")

SPECS: dict[str, BlockSpec] = {s.type: s for s in [
    _spec("from", "source", "FROM", "read_csv", "read_csv",
          "Loads the table. Every cube is one row."),
    _spec("join", "step", "JOIN", "merge", "inner_join",
          "Lines up rows from both tables that share the same key."),
    _spec("where", "step", "WHERE", "filter", "filter",
          "Lights up the rows where the condition holds and drops the rest."),
    _spec("derive", "step", "new column", "assign", "mutate",
          "Works out a new value for every row and adds it as a column."),
    _spec("group", "step", "GROUP BY", "groupby", "group_by",
          "Pulls rows with the same key into piles, then squashes each pile into one row.",
          single=True),
    _spec("having", "step", "HAVING", "filter groups", "filter",
          "Like Where, but for the piles: groups that fail the test are dropped.", single=True),
    _spec("select", "step", "SELECT", "columns", "select",
          "Keeps only the columns you pick.", single=True),
    _spec("order", "step", "ORDER BY", "sort_values", "arrange",
          "Reshuffles the rows by the column you pick.", single=True),
    _spec("limit", "step", "LIMIT", "head", "slice_head",
          "Keeps the first few rows and drops everything after.", single=True),
    # expressions
    _spec("col", "expr", "column", "column", "column"),
    _spec("lit", "expr", "value", "value", "value"),
    _spec("cmp", "expr", "compare", "compare", "compare"),
    _spec("logic", "expr", "and / or", "and / or", "and / or"),
    _spec("not", "expr", "NOT", "not", "!"),
    _spec("math", "expr", "maths", "maths", "maths"),
    _spec("isempty", "expr", "IS NULL", "isna", "is.na"),
    _spec("inlist", "expr", "IN", "isin", "%in%"),
    _spec("text", "expr", "LIKE", "str.contains", "str_detect"),
    _spec("var", "expr", "variable", "variable", "variable", targets=PY_R),
    _spec("field", "expr", "row field", "row field", "row field", targets=PY_R),
    # Python / R only
    _spec("setvar", "python", "—", "Set var", "Set var", "Gives a name a value.", PY_R),
    _spec("changevar", "python", "—", "Change var", "Change var", "Adds to a variable.", PY_R),
    _spec("print", "python", "—", "Print", "Print", "Writes the value to the output.", PY_R),
    _spec("foreach", "python", "—", "For each", "For each",
          "Steps through the results one row at a time.", PY_R),
    _spec("repeat", "python", "—", "Repeat", "Repeat", "Runs the blocks inside n times.", PY_R),
    _spec("if", "python", "—", "If / else", "If / else",
          "Runs the blocks inside only when the test holds.", PY_R),
    _spec("while", "python", "—", "While", "While",
          "Keeps running the blocks inside while the test holds.", PY_R),
    _spec("plot", "plot", "—", "plot", "ggplot", "Draws each result row as a bar.", PY_R),
    _spec("raw", "python", "—", "Code", "Code",
          "Code that can't be shown as blocks yet. It runs as written.", PY_R),
]}


def spec(type: str) -> BlockSpec | None:
    return SPECS.get(type)


STEP_ORDER = ["join", "derive", "where", "group", "having", "select", "order", "limit"]
