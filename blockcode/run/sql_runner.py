"""Run generated SQL against the project's SQLite database (read-only)."""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from blockcode.codegen.emitter import Generated
from blockcode.errors import friendly
from blockcode.run import MAX_ROWS, RunError, RunResult, TableResult

TIMEOUT_S = 10.0  # the same as Python; SQL runs inside the server, so it is stopped from within


def split_statements(gen: Generated) -> list[tuple[str, list[int]]]:
    """Split code into complete statements, keeping the line numbers of each."""
    out: list[tuple[str, list[int]]] = []
    buf: list[str] = []
    nums: list[int] = []
    for ln in gen.lines:
        if not buf and not ln.text.strip():
            continue
        buf.append(ln.text)
        nums.append(ln.n)
        text = "\n".join(buf)
        if sqlite3.complete_statement(text):
            out.append((text, nums))
            buf, nums = [], []
    if buf and "\n".join(buf).strip():
        out.append(("\n".join(buf), nums))
    return out


def _error_line(gen: Generated, nums: list[int], detail: str) -> int:
    """Best guess at the line an SQLite error points to: the first line naming the culprit."""
    m = re.search(r"(?:no such column|no such table|near): \"?([\w.]+)", detail)
    if m:
        word = m.group(1).split(".")[-1]
        for n in nums:
            text = gen.lines[n - 1].text
            if re.search(rf"\b{re.escape(word)}\b", text):
                return n
    return nums[0]


def run_sql(gen: Generated, db_path: Path, names: list[str] | None = None,
            timeout: float = TIMEOUT_S) -> RunResult:
    result = RunResult(target="sql", ok=True)
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    deadline = time.monotonic() + timeout
    # SQLite calls this every few thousand steps; returning 1 interrupts the query
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        for i, (stmt, nums) in enumerate(split_statements(gen)):
            try:
                cur = conn.execute(stmt)
                rows = cur.fetchmany(MAX_ROWS) if cur.description else []
                total = len(rows)
                while cur.description and (more := cur.fetchmany(10_000)):
                    total += len(more)  # count the rest without keeping it
            except sqlite3.Error as exc:
                if time.monotonic() > deadline:
                    result.ok = False
                    result.error = RunError(kind="Timeout", message=friendly("Timeout", "", "sql"),
                                            detail=f"Stopped after {timeout:g} seconds.")
                    return result
                line = _error_line(gen, nums, str(exc))
                blocks = gen.blocks_at(line)
                result.ok = False
                result.error = RunError(kind=type(exc).__name__,
                                        message=friendly(type(exc).__name__, str(exc), "sql"),
                                        detail=str(exc), line=line,
                                        block_id=blocks[0] if blocks else None)
                return result
            if cur.description:
                cols = [d[0] for d in cur.description]
                name = names[i] if names and i < len(names) else f"result {i + 1}"
                result.tables.append(TableResult(name=name, columns=cols,
                                                 rows=[list(r) for r in rows],
                                                 total_rows=total))
    finally:
        conn.close()
    return result
