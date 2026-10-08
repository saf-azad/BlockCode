"""CSV ingest: infer column types, count empty values and load the table into SQLite.

pandas reads every CSV with ``dtype_backend="numpy_nullable"``, the same call the generated
Python uses, so both targets see the same types. Dates stay text in v1.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from blockcode.ir import ColumnInfo, TableInfo

SQL_TYPES = {"int": "INTEGER", "float": "REAL", "bool": "INTEGER", "text": "TEXT"}


def table_name_for(filename: str) -> str:
    stem = Path(filename).stem.lower()
    name = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_") or "table"
    if name[0].isdigit():
        name = "t_" + name
    return name


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype_backend="numpy_nullable")


def column_type(series: pd.Series) -> str:
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(dtype):
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    return "text"


def inspect(df: pd.DataFrame, name: str, file: str) -> TableInfo:
    cols = [ColumnInfo(name=str(c), type=column_type(df[c]), empty=int(df[c].isna().sum()))
            for c in df.columns]
    return TableInfo(name=name, file=file, rows=len(df), columns=cols)


def load_into_sqlite(conn: sqlite3.Connection, df: pd.DataFrame, info: TableInfo) -> None:
    q = lambda s: '"' + s.replace('"', '""') + '"'  # noqa: E731
    conn.execute(f"DROP TABLE IF EXISTS {q(info.name)}")
    cols = ", ".join(f"{q(c.name)} {SQL_TYPES[c.type]}" for c in info.columns)
    conn.execute(f"CREATE TABLE {q(info.name)} ({cols})")
    rows = [
        tuple(None if pd.isna(v) else (int(v) if isinstance(v, bool) else v) for v in row)
        for row in df.astype(object).itertuples(index=False, name=None)
    ]
    marks = ", ".join("?" for _ in info.columns)
    conn.executemany(f"INSERT INTO {q(info.name)} VALUES ({marks})", rows)
    conn.commit()


def ingest(csv_path: Path, project_dir: Path, db_path: Path, name: str | None = None) -> TableInfo:
    """Inspect a CSV that already sits in ``project_dir/data`` and load it into the project DB."""
    df = read_csv(csv_path)
    info = inspect(df, name or table_name_for(csv_path.name),
                   csv_path.relative_to(project_dir).as_posix())
    with sqlite3.connect(db_path) as conn:
        load_into_sqlite(conn, df, info)
    return info
