"""Line emitter that tags each line with the blocks that produced it (the source map)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from blockcode.diagnostics import Diagnostic


class Line(BaseModel):
    n: int
    text: str
    blocks: list[str] = Field(default_factory=list)


class Generated(BaseModel):
    target: str
    code: str
    lines: list[Line]
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    ok: bool = True  # False when the program can't be expressed in this target

    def lines_for(self, block_id: str) -> list[int]:
        return [ln.n for ln in self.lines if block_id in ln.blocks]

    def blocks_at(self, line: int) -> list[str]:
        return next((ln.blocks for ln in self.lines if ln.n == line), [])


class Emitter:
    def __init__(self, indent: str = "    ") -> None:
        self._lines: list[tuple[str, list[str]]] = []
        self._indent = indent
        self.depth = 0

    def emit(self, text: str, *blocks: str | None) -> None:
        for part in text.split("\n"):
            prefix = self._indent * self.depth if part else ""
            self._lines.append((prefix + part, [b for b in blocks if b]))

    def blank(self) -> None:
        if self._lines and self._lines[-1][0] != "":
            self._lines.append(("", []))

    def tag_last(self, *blocks: str) -> None:
        text, tags = self._lines[-1]
        self._lines[-1] = (text, tags + [b for b in blocks if b not in tags])

    def __len__(self) -> int:
        return len(self._lines)

    def result(self, target: str, diagnostics: list[Diagnostic] | None = None,
               ok: bool = True) -> Generated:
        lines = list(self._lines)
        while lines and lines[-1][0] == "":
            lines.pop()
        out = [Line(n=i + 1, text=t, blocks=b) for i, (t, b) in enumerate(lines)]
        code = "\n".join(t for t, _ in lines) + ("\n" if lines else "")
        return Generated(target=target, code=code, lines=out, diagnostics=diagnostics or [], ok=ok)
