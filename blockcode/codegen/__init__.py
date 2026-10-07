"""Code generators: Program → SQL, Python (pandas) or R (dplyr), each with a source map."""

from __future__ import annotations

from blockcode.codegen.emitter import Generated
from blockcode.ir import Program, TableInfo

TARGETS = ("sql", "python", "r")


def generate(program: Program, tables: dict[str, TableInfo] | list[TableInfo], target: str,
             **options) -> Generated:
    if isinstance(tables, list):
        tables = {t.name: t for t in tables}
    if target == "sql":
        from blockcode.codegen.sql import generate_sql
        return generate_sql(program, tables)
    if target == "python":
        from blockcode.codegen.python import generate_python
        return generate_python(program, tables)
    if target == "r":
        from blockcode.codegen.r import generate_r
        return generate_r(program, tables, **options)
    raise ValueError(f"Unknown target {target!r}; pick one of {', '.join(TARGETS)}")
