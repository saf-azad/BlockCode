"""CSV ingest: tidy the file, infer column types, count empty values and load it into SQLite.

Every uploaded file is first rewritten by :func:`normalize_csv` into one plain shape (UTF-8,
comma separated, tidy headers, one spelling of "empty"), so that pandas, readr and the SQLite
load all read the same table with their default settings. pandas then reads it with
``dtype_backend="numpy_nullable"``, the same call the generated Python uses, so both targets see
the same types. Dates stay text in v1.
"""

from __future__ import annotations

import csv
import io
import keyword
import re
import sqlite3
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from blockcode.ir import ColumnInfo, TableInfo

SQL_TYPES = {"int": "INTEGER", "float": "REAL", "bool": "INTEGER", "text": "TEXT"}
INT64_MAX = 2**63 - 1
# one uploaded file is at most ~10 MB, so a single field can't be larger; raise the default
# 128 KB limit so a long text cell is read as one value instead of crashing the CSV reader
csv.field_size_limit(16 * 1024 * 1024)

# pandas' default "empty" spellings. readr only knows "" and "NA", so everything here is
# rewritten as "" and all three languages agree on which values are empty.
NA_TOKENS = {"", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND",
             "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null"}
DELIMITERS = [",", ";", "\t", "|"]
# Table names become Python variables, so they can't be keywords or shadow what the
# generated code uses.
# R's reserved words, so an uploaded table named "function" or "next" still runs in R
R_RESERVED = {"if", "else", "repeat", "while", "function", "for", "next", "break", "true",
              "false", "null", "inf", "nan", "na", "in", "t", "f"}
TAKEN_NAMES = (set(keyword.kwlist) | R_RESERVED
               | {"pd", "plt", "np", "print", "len", "range", "round", "str",
                  "int", "float", "sum", "min", "max", "abs", "list", "type"})

_PLAIN_NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")
_THOUSANDS = re.compile(r"^[-+]?\d{1,3}(,\d{3})+(\.\d+)?$")
_EU_NUM = re.compile(r"^[-+]?\d{1,3}(\.\d{3})*(,\d+)?$|^[-+]?\d+(,\d+)?$")
_LEADING_ZEROS = re.compile(r"^([-+]?)0+(?=\d)")


class CsvError(ValueError):
    """A file we can't turn into a table; the message is shown to the learner."""


class Normalized(BaseModel):
    text: str
    notes: list[str] = Field(default_factory=list)  # what we changed, in plain words


MAX_NAME = 60  # table names become variables and file names: keep them readable


def table_name_for(filename: str) -> str:
    stem = Path(filename).stem.lower()
    name = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_")[:MAX_NAME].rstrip("_") or "table"
    if name[0].isdigit():
        name = "t_" + name
    if name in TAKEN_NAMES:
        name += "_data"
    return name


def _decode(content: bytes) -> tuple[str, str | None]:
    """Text of the file and, if it wasn't UTF-8, the encoding we used."""
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16"), "UTF-16"
    if content.startswith(b"PK\x03\x04") or content.startswith(b"\xd0\xcf\x11\xe0"):
        raise CsvError("This looks like an Excel workbook. Save it as CSV first "
                       "(File → Save As → CSV) and drop that file here.")
    try:
        return content.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        pass
    try:
        return content.decode("cp1252"), "Windows-1252"
    except UnicodeDecodeError:
        return content.decode("latin-1"), "Latin-1"


def _looks_binary(text: str) -> bool:
    sample = text[:20000]
    if "\x00" in sample:
        return True
    odd = sum(1 for ch in sample if ord(ch) < 32 and ch not in "\t\r\n")
    return odd > max(2, len(sample) // 100)


def _sniff(text: str) -> str:
    """The delimiter that splits the first lines into the most columns, consistently."""
    sample = "\n".join(text.splitlines()[:60])
    best, best_score = ",", (0.0, 0)
    for d in DELIMITERS:
        widths = [len(r) for r in csv.reader(io.StringIO(sample), delimiter=d) if any(r)]
        if not widths or widths[0] < 2:
            continue
        consistent = sum(1 for w in widths if w == widths[0]) / len(widths)
        score = (round(consistent, 2), widths[0])
        if score > best_score:
            best, best_score = d, score
    return best


def _clean_headers(header: list[str], notes: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    blank = renamed = 0
    for i, raw in enumerate(header):
        # control characters can't be typed or shown, so they go; runs of spaces become one
        name = re.sub(r"\s+", " ", re.sub(r"[\x00-\x08\x0e-\x1f\x7f]", "", raw)).strip()
        if not name:
            name = f"column_{i + 1}"
            blank += 1
        base, n = name, 2
        while name.lower() in seen:  # SQL column names ignore case
            name = f"{base}_{n}"
            n += 1
        if name != base:
            renamed += 1
        seen.add(name.lower())
        out.append(name)
    if blank:
        notes.append(f"Named {blank} column{'s' if blank > 1 else ''} that had no header.")
    if renamed:
        notes.append(f"Renamed {renamed} repeated column name{'s' if renamed > 1 else ''}.")
    return out


def _clean_numbers(name: str, values: list[str], delimiter: str, notes: list[str]) -> list[str]:
    """Make a column of numbers read as numbers everywhere: drop thousands separators
    ("1,234"), turn decimal commas into points in semicolon files ("1,5"), and drop leading
    zeros ("007"), which pandas ignores but readr would keep as text."""
    filled = [v for v in values if v]
    if not filled:
        return values
    changed = False
    if all(_PLAIN_NUM.match(v) for v in filled):
        out = values
    elif delimiter == ";" and all(_EU_NUM.match(v) for v in filled):
        out = [v.replace(".", "").replace(",", ".") if v else v for v in values]
        notes.append(f"Read {name} as numbers with decimal commas.")
        changed = True
    elif all(_PLAIN_NUM.match(v) or _THOUSANDS.match(v) for v in filled):
        out = [v.replace(",", "") for v in values]
        notes.append(f"Removed the thousands separators in {name}.")
        changed = True
    else:
        return values
    stripped = [_LEADING_ZEROS.sub(r"\1", v) for v in out]
    if stripped != out and not changed:
        notes.append(f"Read {name} as numbers (leading zeros dropped).")
    return stripped


def normalize_csv(content: bytes) -> Normalized:
    """Rewrite a delimited text file as a tidy UTF-8 CSV, or raise CsvError saying why not."""
    if not content.strip():
        raise CsvError("That file is empty.")
    text, encoding = _decode(content)
    # old-Mac files use lone CRs and some Windows files use CRLF; make every line end in \n so
    # the CSV reader doesn't see a stray newline inside a field
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if _looks_binary(text):
        raise CsvError("That file doesn't look like a CSV. Save your data as CSV (comma "
                       "separated values) and try again.")
    notes: list[str] = []
    if encoding:
        notes.append(f"Read the file as {encoding} text.")
    delimiter = _sniff(text)
    if delimiter != ",":
        notes.append({";": "Split columns on semicolons.", "\t": "Split columns on tabs.",
                      "|": "Split columns on | bars."}[delimiter])
    try:
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter)
                if any(c.strip() for c in r)]
    except csv.Error as exc:
        raise CsvError(f"That file doesn't look like a CSV I can read: {exc}") from exc
    if not rows:
        raise CsvError("That file is empty.")
    width = max(len(r) for r in rows)
    short = sum(1 for r in rows[1:] if len(r) < width)
    if len(rows[0]) < width:
        notes.append("Some rows have more values than there are headers; the extra columns "
                     "were given names.")
    elif short:
        notes.append(f"Filled {short} short row{'s' if short > 1 else ''} with empty values.")
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = _clean_headers(rows[0], notes)
    body = rows[1:]
    columns = [[r[i].strip() for r in body] for i in range(width)]
    if any(v in NA_TOKENS and v for col in columns for v in col):
        notes.append("Treated NA, N/A, null and similar values as empty.")
    columns = [["" if v in NA_TOKENS else v for v in col] for col in columns]
    columns = [_clean_numbers(header[i], col, delimiter, notes) for i, col in enumerate(columns)]

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    if body:
        w.writerows(zip(*columns))
    return Normalized(text=buf.getvalue(), notes=notes)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype_backend="numpy_nullable")


def column_type(series: pd.Series) -> str:
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(dtype):
        # integers too big for SQLite (and R) are stored as decimals
        if len(series.dropna()) and series.dropna().max() > INT64_MAX:
            return "float"
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    return "text"


def _typical(s: pd.Series, kind: str) -> int | float | str | None:
    """A value new blocks can start from so they keep some rows: the median of a number
    column (rounded to look hand-typed), the most common text."""
    filled = s.dropna()
    if not len(filled):
        return None
    if kind in ("int", "float"):
        m = float(filled.astype("float64").median())
        if kind == "int" or abs(m) >= 100:
            return int(round(m))
        return round(m, 2 if abs(m) >= 1 else 3)
    if kind == "text":
        return str(filled.value_counts().index[0])[:80]
    return None


def inspect(df: pd.DataFrame, name: str, file: str) -> TableInfo:
    cols = []
    for c in df.columns:
        s = df[c]
        kind = column_type(s)
        empty = int(s.isna().sum())
        unique = len(s) > 0 and empty == 0 and bool(s.is_unique)
        cols.append(ColumnInfo(name=str(c), type=kind, empty=empty, unique=unique,
                               typical=_typical(s, kind)))
    return TableInfo(name=name, file=file, rows=len(df), columns=cols)


def _sql_value(v, kind: str):
    if v is None or (not isinstance(v, (list, tuple)) and pd.isna(v)):
        return None
    if isinstance(v, bool):
        return int(v)
    if kind == "float" and isinstance(v, int):
        return float(v)
    return v


def load_into_sqlite(conn: sqlite3.Connection, df: pd.DataFrame, info: TableInfo) -> None:
    q = lambda s: '"' + s.replace('"', '""') + '"'  # noqa: E731
    conn.execute(f"DROP TABLE IF EXISTS {q(info.name)}")
    cols = ", ".join(f"{q(c.name)} {SQL_TYPES[c.type]}" for c in info.columns)
    conn.execute(f"CREATE TABLE {q(info.name)} ({cols})")
    kinds = [c.type for c in info.columns]
    rows = [tuple(_sql_value(v, k) for v, k in zip(row, kinds))
            for row in df.astype(object).itertuples(index=False, name=None)]
    marks = ", ".join("?" for _ in info.columns)
    conn.executemany(f"INSERT INTO {q(info.name)} VALUES ({marks})", rows)
    conn.commit()


def ingest(csv_path: Path, project_dir: Path, db_path: Path, name: str | None = None) -> TableInfo:
    """Inspect a CSV that already sits in ``project_dir/data`` and load it into the project DB."""
    df = read_csv(csv_path)
    if len(df.columns) == 0:
        raise CsvError("That file has no columns.")
    info = inspect(df, name or table_name_for(csv_path.name),
                   csv_path.relative_to(project_dir).as_posix())
    with sqlite3.connect(db_path) as conn:
        load_into_sqlite(conn, df, info)
    return info


def add_table(project_dir: Path, db_path: Path, filename: str, content: bytes,
              name: str | None = None) -> tuple[TableInfo, list[str]]:
    """Tidy an uploaded file into ``project_dir/data/<table>.csv`` and load it into the DB.
    Returns the table and notes on what was tidied; raises CsvError if it can't be read."""
    table = name or table_name_for(filename)
    norm = normalize_csv(content)
    dest = project_dir / "data" / f"{table}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(norm.text.encode("utf-8"))
    try:
        return ingest(dest, project_dir, db_path, table), norm.notes
    except CsvError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:  # pandas raises many kinds of parse errors
        dest.unlink(missing_ok=True)
        raise CsvError(f"That file doesn't look like a CSV I can read: {exc}") from exc
