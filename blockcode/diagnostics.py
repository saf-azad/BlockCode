"""Problems reported to the learner. Each one points at a block (and, after codegen, a line)."""

from __future__ import annotations

from pydantic import BaseModel


class Diagnostic(BaseModel):
    severity: str  # "error" | "warning" | "sql" (no SQL equivalent) | "info"
    message: str
    block_id: str | None = None
    line: int | None = None  # 1-based line in the generated or typed code
    target: str | None = None  # the target this applies to, if only one


def error(message: str, block_id: str | None = None, **kw) -> Diagnostic:
    return Diagnostic(severity="error", message=message, block_id=block_id, **kw)


def warning(message: str, block_id: str | None = None, **kw) -> Diagnostic:
    return Diagnostic(severity="warning", message=message, block_id=block_id, **kw)
