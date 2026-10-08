"""Runners: execute generated code and map errors back to blocks."""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_ROWS = 200
MAX_STDOUT = 100_000  # characters of printing to send back (a runaway loop can print megabytes)


def clip_output(out: str) -> str:
    if len(out) <= MAX_STDOUT:
        return out
    return out[:MAX_STDOUT] + f"\n… and {len(out) - MAX_STDOUT:,} more characters of printing.\n"


class TableResult(BaseModel):
    name: str
    columns: list[str]
    rows: list[list]
    total_rows: int


class RunError(BaseModel):
    kind: str  # e.g. "NameError", "sqlite3.OperationalError", "Timeout"
    message: str  # friendly message for learners
    detail: str = ""  # the raw error text
    line: int | None = None
    block_id: str | None = None


class RunResult(BaseModel):
    target: str
    ok: bool
    tables: list[TableResult] = Field(default_factory=list)
    stdout: str = ""
    plots: list[str] = Field(default_factory=list)  # base64 PNGs
    error: RunError | None = None
    code: str = ""  # the code that ran, so the editor can tell when its results are out of date
