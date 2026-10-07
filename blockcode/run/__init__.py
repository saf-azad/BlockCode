"""Runners: execute generated code and map errors back to blocks."""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_ROWS = 200


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
