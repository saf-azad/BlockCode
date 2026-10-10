"""Program IR shared by the editor, the CLI and every code generator and parser.

A program is a list of top-level blocks. Each block has:

* ``fields``: plain values chosen in the block (a table, a column, an operator, a number)
* ``inputs``: expression slots holding one expression block each (``cond``, ``a``, ``b`` ...)
* ``stacks``: named lists of child blocks (``steps`` of a From block, ``body`` of a For each)

Data pipelines are a ``from`` block whose ``steps`` stack holds the clause blocks
(join, where, derive, group, having, select, order, limit) in clause order.
"""

from __future__ import annotations

from itertools import count
from typing import Any, Iterator

from pydantic import BaseModel, Field


class Block(BaseModel):
    id: str
    type: str
    fields: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Block] = Field(default_factory=dict)
    stacks: dict[str, list[Block]] = Field(default_factory=dict)

    def field(self, name: str, default: Any = None) -> Any:
        return self.fields.get(name, default)

    def stack(self, name: str) -> list[Block]:
        return self.stacks.get(name, [])

    def walk(self) -> Iterator[Block]:
        """This block and every block nested inside it, depth first."""
        yield self
        for child in self.inputs.values():
            yield from child.walk()
        for stack in self.stacks.values():
            for child in stack:
                yield from child.walk()


class Program(BaseModel):
    blocks: list[Block] = Field(default_factory=list)

    def walk(self) -> Iterator[Block]:
        for block in self.blocks:
            yield from block.walk()

    def find(self, block_id: str) -> Block | None:
        return next((b for b in self.walk() if b.id == block_id), None)


class ColumnInfo(BaseModel):
    name: str
    type: str  # "int" | "float" | "text" | "bool"
    empty: int = 0
    unique: bool = False  # every value filled and different (a key candidate)
    typical: int | float | str | None = None  # median number or most common text (for defaults)


class TableInfo(BaseModel):
    name: str
    file: str  # path relative to the project directory, e.g. "data/students.csv"
    rows: int
    columns: list[ColumnInfo]

    def column(self, name: str) -> ColumnInfo | None:
        return next((c for c in self.columns if c.name == name), None)


class Project(BaseModel):
    version: int = 1
    name: str
    title: str = ""
    tables: list[TableInfo] = Field(default_factory=list)
    program: Program = Field(default_factory=Program)

    def table(self, name: str) -> TableInfo | None:
        return next((t for t in self.tables if t.name == name), None)


_ids = count(1)


def new_id(prefix: str = "b") -> str:
    return f"{prefix}{next(_ids)}"
