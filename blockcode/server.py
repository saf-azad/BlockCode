"""FastAPI server: a stateless JSON API under /api and the built web app at /.

The server keeps nothing between requests. Each visitor's tables and blocks live in their own
browser. A request that runs or exports code carries the CSVs it needs; they are tidied into a
temporary folder, used, and thrown away. Visitors never see each other's data, and it works the
same on one machine as on serverless hosts like Vercel, where requests land on different
instances.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import sqlite3
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from blockcode import __version__
from blockcode.codegen import TARGETS, generate
from blockcode.data_io import CsvError, add_table, table_name_for
from blockcode.ir import Program, TableInfo
from blockcode.registry import SPECS, STEP_ORDER
from blockcode.run import RunError, RunResult

ROOT = Path(__file__).resolve().parent.parent
# The built web app: web/dist locally, public/ when the Vercel build puts it there.
WEB_DIRS = (ROOT / "web" / "dist", ROOT / "public")
MAX_FILE = 10 * 1024 * 1024  # one CSV, after unzipping
MAX_TABLES = 30
TOO_BIG = f"That file is too big ({MAX_FILE // (1024 * 1024)} MB max)."
OOPS = ("Something went wrong inside BlockCode with these blocks. Undo your last change, or "
        "remove the block you just edited, and try again.")
# A "Code" (raw) block holds free-typed Python or R that runs on the server exactly as written.
# On a shared, public deployment that lets anyone run arbitrary code, so running it is off unless
# the operator opts in with BLOCKCODE_ALLOW_RAW_CODE on a trusted or sandboxed host. Showing and
# exporting code are never affected, and programs built only from blocks always run.
RAW_OFF = ("Running free-typed code is turned off on this server, so a program with a Code block "
           "can't be run here. The blocks around it still run, and you can still show and export "
           "the code. Rebuild the Code block as blocks to run it.")
_TRUTHY = {"1", "true", "yes", "on"}
log = logging.getLogger("blockcode")


def raw_code_allowed() -> bool:
    return os.environ.get("BLOCKCODE_ALLOW_RAW_CODE", "").strip().lower() in _TRUTHY


def raw_run_refusal(program: Program, target: str) -> dict | None:
    """When free-typed code is off, refuse to run a program that contains a Code block,
    pointing at the first one so the editor can highlight it. Returns ``None`` otherwise."""
    if raw_code_allowed():
        return None
    first = next((b for b in program.walk() if b.type == "raw"), None)
    if first is None:
        return None
    return RunResult(target=target, ok=False,
                     error=RunError(kind="RawCodeBlocked", message=RAW_OFF,
                                    block_id=first.id)).model_dump()


class GenerateIn(BaseModel):
    program: Program
    tables: list[TableInfo] = Field(default_factory=list)
    title: str = ""


class ParseIn(BaseModel):
    code: str
    lang: str
    tables: list[TableInfo] = Field(default_factory=list)
    previous: Program | None = None


class TablesIn(BaseModel):
    tables: list[TableInfo] = Field(default_factory=list)


class RunIn(BaseModel):
    program: Program
    target: str = "sql"
    title: str = ""


def target_ok(target: str) -> str:
    if target not in TARGETS:
        raise HTTPException(400, f"target must be one of {', '.join(TARGETS)}")
    return target


def unzip(content: bytes) -> bytes:
    """The browser gzips CSVs before sending them; plain files are accepted too."""
    if len(content) > MAX_FILE:
        raise HTTPException(413, TOO_BIG)
    if not content.startswith(b"\x1f\x8b"):
        return content
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = d.decompress(content, MAX_FILE + 1)
    except zlib.error as exc:
        raise HTTPException(400, "That file arrived damaged. Please try again.") from exc
    if len(out) > MAX_FILE:
        raise HTTPException(413, TOO_BIG)
    return out


def table_name(filename: str) -> str:
    return table_name_for(re.sub(r"(\.gz)?$", "", filename or "table.csv"))


async def read_files(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    if len(files) > MAX_TABLES:
        raise HTTPException(400, f"At most {MAX_TABLES} tables at a time.")
    return [(table_name(f.filename or "table.csv"), unzip(await f.read(MAX_FILE + 1)))
            for f in files]


@contextmanager
def workspace(files: list[tuple[str, bytes]]) -> Iterator[tuple[Path, Path, list[TableInfo]]]:
    """A throwaway folder with ``data/<table>.csv`` and ``db.sqlite`` built from the uploads."""
    with TemporaryDirectory(prefix="blockcode-ws-") as tmp:
        d = Path(tmp)
        db = d / "db.sqlite"
        sqlite3.connect(db).close()
        tables: list[TableInfo] = []
        for name, content in files:
            try:
                info, _ = add_table(d, db, f"{name}.csv", content, name=name)
            except CsvError as exc:
                raise HTTPException(400, f"{name}: {exc}") from exc
            tables = [t for t in tables if t.name != info.name] + [info]
        yield d, db, tables


def parse_run(request: str) -> RunIn:
    try:
        body = RunIn.model_validate(json.loads(request))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, "The request was not understood.") from exc
    target_ok(body.target)
    return body


def create_app() -> FastAPI:
    from blockcode.run.sandbox import protect_server_process

    protect_server_process()
    app = FastAPI(title="BlockCode", version=__version__)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unexpected error on %s", request.url.path)
        return JSONResponse({"detail": OOPS}, status_code=500)

    @app.get("/api/health")
    def health() -> dict:
        from blockcode.run.r_runner import rscript

        return {"ok": True, "version": __version__, "r": rscript() is not None,
                "max_file": MAX_FILE}

    @app.get("/api/blocks")
    def blocks() -> dict:
        return {"blocks": [s.model_dump() for s in SPECS.values()], "step_order": STEP_ORDER}

    @app.post("/api/tables")
    async def inspect_table(file: UploadFile = File(...)) -> dict:
        """Read an uploaded CSV: its columns, types and empty counts, plus notes on anything
        that was tidied. The file itself is not kept."""
        name = table_name(file.filename or "table.csv")
        content = unzip(await file.read(MAX_FILE + 1))

        def work() -> dict:
            with TemporaryDirectory(prefix="blockcode-in-") as tmp:
                d = Path(tmp)
                try:
                    info, notes = add_table(d, d / "db.sqlite", f"{name}.csv", content, name=name)
                except CsvError as exc:
                    raise HTTPException(400, str(exc)) from exc
            return {"table": info.model_dump(), "notes": notes}

        return await run_in_threadpool(work)

    @app.post("/api/generate-all")
    def gen_all(body: GenerateIn) -> dict:
        """Code, source map and problems for every language at once (the editor shows the
        hovered block in all three)."""
        from blockcode.validate import validate

        from blockcode.codegen.emitter import Generated
        from blockcode.diagnostics import error

        tables = {t.name: t for t in body.tables}
        out = {}
        for t in TARGETS:
            extra = {"title": body.title or "BlockCode"} if t == "r" else {}
            try:
                g = generate(body.program, tables, t, **extra)
                g.diagnostics = validate(body.program, tables, t, generated=g)
            except Exception:  # one language failing shouldn't take the others down
                log.exception("generate %s failed", t)
                g = Generated(target=t, code="", lines=[], diagnostics=[error(OOPS)], ok=False)
            out[t] = g.model_dump()
        return out

    @app.post("/api/parse")
    def parse(body: ParseIn) -> dict:
        from blockcode.parse import parse_code

        return parse_code(body.code, target_ok(body.lang), body.tables,
                          previous=body.previous).model_dump()

    @app.post("/api/erd")
    def erd(body: TablesIn) -> dict:
        from blockcode.erd import infer_erd

        return infer_erd(body.tables).model_dump()

    @app.post("/api/run")
    async def run(request: str = Form(...), files: list[UploadFile] = File(default=[])) -> dict:
        from blockcode.engine import run_in

        body = parse_run(request)
        refusal = raw_run_refusal(body.program, body.target)
        if refusal is not None:
            return refusal
        data = await read_files(files)

        def work() -> dict:
            with workspace(data) as (d, db, tables):
                return run_in(d, db, tables, body.program, body.target).model_dump()

        return await run_in_threadpool(work)

    @app.post("/api/export")
    async def export(request: str = Form(...),
                     files: list[UploadFile] = File(default=[])) -> Response:
        from blockcode.export import export_files
        from blockcode.project_io import ProjectError

        body = parse_run(request)
        data = await read_files(files)
        stem = re.sub(r"[^A-Za-z0-9]+", "_", body.title).strip("_").lower() or "analysis"

        def work() -> bytes:
            with workspace(data) as (d, db, tables), TemporaryDirectory() as out_dir:
                out = Path(out_dir)
                try:
                    written = export_files(d, db, tables, body.program, body.target, out,
                                           title=body.title or "BlockCode", stem=stem)
                except ProjectError as exc:
                    raise HTTPException(400, str(exc)) from exc
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in written:
                        z.write(f, f.relative_to(out).as_posix())
                return buf.getvalue()

        content = await run_in_threadpool(work)
        fname = f"{stem}-{body.target}.zip"
        return Response(content, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    web = next((d for d in WEB_DIRS if (d / "index.html").is_file()), None)
    if web is not None:
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app


# Module-level app for ASGI hosts: Vercel (see [tool.vercel] in pyproject.toml) and
# `uvicorn blockcode.server:app`. `blockcode serve` builds its own with create_app().
app = create_app()
