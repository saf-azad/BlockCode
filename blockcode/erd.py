"""Infer a quick ERD: columns with the same name in two tables are treated as links.

The side where the column's values are unique (and never empty) is the "one" side and its
column is a primary key; the other side is "many" and holds a foreign key.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field

from blockcode.ir import TableInfo


class ErdColumn(BaseModel):
    name: str
    type: str
    pk: bool = False
    fk: bool = False


class ErdTable(BaseModel):
    name: str
    rows: int
    columns: list[ErdColumn]


class ErdLink(BaseModel):
    column: str
    one: str  # table on the "1" side (or the first table when neither side is unique)
    many: str
    kind: str  # "1-*", "1-1" or "*-*"


class Erd(BaseModel):
    tables: list[ErdTable] = Field(default_factory=list)
    links: list[ErdLink] = Field(default_factory=list)
    unlinked: list[tuple[str, str]] = Field(default_factory=list)  # table pairs with no link


def _unique(conn: sqlite3.Connection, table: str, column: str) -> bool:
    q = lambda s: '"' + s.replace('"', '""') + '"'  # noqa: E731
    total, distinct, filled = conn.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT {q(column)}), COUNT({q(column)}) FROM {q(table)}"
    ).fetchone()
    return total > 0 and distinct == total == filled


def infer_erd(tables: list[TableInfo], db_path: Path) -> Erd:
    erd = Erd(tables=[ErdTable(name=t.name, rows=t.rows,
                               columns=[ErdColumn(name=c.name, type=c.type) for c in t.columns])
                      for t in tables])
    by_name = {t.name: t for t in erd.tables}
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) if db_path.exists() \
        else None
    try:
        for i, a in enumerate(tables):
            for b in tables[i + 1:]:
                shared = [c.name for c in a.columns if b.column(c.name)]
                found = 0
                for col in shared:
                    ua = _unique(conn, a.name, col) if conn else False
                    ub = _unique(conn, b.name, col) if conn else False
                    if ua and ub:
                        link = ErdLink(column=col, one=a.name, many=b.name, kind="1-1")
                    elif ua:
                        link = ErdLink(column=col, one=a.name, many=b.name, kind="1-*")
                    elif ub:
                        link = ErdLink(column=col, one=b.name, many=a.name, kind="1-*")
                    elif col.lower().endswith("id"):
                        link = ErdLink(column=col, one=a.name, many=b.name, kind="*-*")
                    else:
                        # a shared name like "name" or "date", unique on neither side, is
                        # almost always a coincidence rather than a link
                        continue
                    erd.links.append(link)
                    found += 1
                    for t, col_is_key in ((link.one, link.kind != "*-*"), (link.many, False)):
                        c = next(x for x in by_name[t].columns if x.name == col)
                        if col_is_key:
                            c.pk = True
                        elif t == link.many:
                            c.fk = True
                if not found:
                    erd.unlinked.append((a.name, b.name))
    finally:
        if conn:
            conn.close()
    return erd
