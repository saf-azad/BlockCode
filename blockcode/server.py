"""FastAPI server: JSON API under /api and the built web app at /."""

from __future__ import annotations

import io
import os
import tempfile
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from blockcode import __version__
from blockcode.codegen import TARGETS, generate
from blockcode.engine import BROWSER_TARGETS, Raw
from blockcode.ir import Program, Project
from blockcode.project_io import ProjectError, ProjectStore
from blockcode.registry import SPECS, STEP_ORDER

ROOT = Path(__file__).resolve().parent.parent
# The built web app: web/dist locally, public/ when the Vercel build puts it there.
WEB_DIRS = (ROOT / "web" / "dist", ROOT / "public")
MAX_UPLOAD = 20 * 1024 * 1024


def default_projects_dir() -> Path:
    """Where projects live: $BLOCKCODE_PROJECTS_DIR, else /tmp on Vercel (the only writable
    place there, and not kept between cold starts), else ./projects."""
    if os.environ.get("BLOCKCODE_PROJECTS_DIR"):
        return Path(os.environ["BLOCKCODE_PROJECTS_DIR"])
    if os.environ.get("VERCEL"):
        return Path(tempfile.gettempdir()) / "blockcode-projects"
    return Path("projects")


class ProgramIn(BaseModel):
    program: Program
    target: str = "sql"


class ParseIn(BaseModel):
    code: str
    lang: str
    previous: Program | None = None


class FinishIn(BaseModel):
    program: Program
    target: str
    raw: Raw


# Python and R run in the learner's browser, from these WebAssembly builds. Point them at your
# own copies to self-host, or set BLOCKCODE_RUN_IN=server to run on this machine instead.
PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs"
WEBR_URL = "https://webr.r-wasm.org/v0.6.0/webr.mjs"
WEBR_REPO = "https://repo.r-wasm.org/"


def runtime_config() -> dict:
    env = os.environ.get
    return {
        "run_in": "server" if env("BLOCKCODE_RUN_IN", "browser") == "server" else "browser",
        "pyodide": env("BLOCKCODE_PYODIDE_URL", PYODIDE_URL),
        "webr": env("BLOCKCODE_WEBR_URL", WEBR_URL),
        "webr_repo": env("BLOCKCODE_WEBR_REPO", WEBR_REPO),
    }


class NewProject(BaseModel):
    name: str
    title: str = ""
    sample: bool = True


def create_app(projects_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="BlockCode", version=__version__)
    store = ProjectStore(Path(projects_dir or default_projects_dir()).resolve())
    app.state.store = store

    def load(name: str) -> Project:
        try:
            return store.load(name)
        except ProjectError as exc:
            raise HTTPException(404, str(exc)) from exc

    def target_ok(target: str) -> str:
        if target not in TARGETS:
            raise HTTPException(400, f"target must be one of {', '.join(TARGETS)}")
        return target

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/blocks")
    def blocks() -> dict:
        return {"blocks": [s.model_dump() for s in SPECS.values()], "step_order": STEP_ORDER}

    @app.get("/api/projects")
    def projects() -> dict:
        return {"projects": store.list()}

    @app.post("/api/projects")
    def create_project(body: NewProject) -> Project:
        try:
            return store.create(body.name, body.title, sample=body.sample)
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/projects/{name}")
    def get_project(name: str) -> Project:
        """Opening a project that doesn't exist yet creates it with the school sample."""
        if not store.exists(name):
            try:
                return store.create(name)
            except ProjectError as exc:
                raise HTTPException(400, str(exc)) from exc
        return load(name)

    @app.put("/api/projects/{name}/program")
    def save_program(name: str, program: Program) -> dict:
        load(name)
        store.save_program(name, program)
        return {"ok": True}

    @app.post("/api/projects/{name}/data")
    async def upload(name: str, file: UploadFile = File(...)) -> dict:
        load(name)
        content = await file.read()
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "That file is too big (20 MB max).")
        if not (file.filename or "").lower().endswith(".csv"):
            raise HTTPException(400, "Only .csv files can be dropped here.")
        try:
            info = store.add_csv(name, file.filename or "table.csv", content)
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"table": info.model_dump()}

    @app.post("/api/projects/{name}/generate")
    def gen(name: str, body: ProgramIn) -> dict:
        project = load(name)
        target = target_ok(body.target)
        extra = {"title": project.title or project.name} if target == "r" else {}
        return generate(body.program, project.tables, target, **extra).model_dump()

    @app.post("/api/projects/{name}/generate-all")
    def gen_all(name: str, body: ProgramIn) -> dict:
        """Code, source map and problems for every language at once (the editor shows the
        hovered block in all three)."""
        from blockcode.validate import validate

        project = load(name)
        tables = {t.name: t for t in project.tables}
        out = {}
        for t in TARGETS:
            extra = {"title": project.title or project.name} if t == "r" else {}
            g = generate(body.program, tables, t, **extra)
            g.diagnostics = validate(body.program, tables, t, generated=g)
            out[t] = g.model_dump()
        return out

    @app.get("/api/examples")
    def examples() -> dict:
        from blockcode.examples import TITLES

        return {"examples": [{"name": k, "title": v} for k, v in TITLES.items()]}

    @app.get("/api/examples/{example}")
    def example(example: str) -> Program:
        from blockcode.examples import school

        progs = school()
        if example not in progs:
            raise HTTPException(404, "No such example.")
        return progs[example]

    @app.post("/api/projects/{name}/validate")
    def check(name: str, body: ProgramIn) -> dict:
        from blockcode.validate import validate

        project = load(name)
        tables = {t.name: t for t in project.tables}
        diags = validate(body.program, tables, target_ok(body.target))
        return {"diagnostics": [d.model_dump() for d in diags]}

    @app.post("/api/projects/{name}/run")
    def run(name: str, body: ProgramIn) -> dict:
        from blockcode.engine import run as run_program

        project = load(name)
        return run_program(store, project, body.program, target_ok(body.target)).model_dump()

    @app.get("/api/runtime")
    def runtime() -> dict:
        return runtime_config()

    @app.post("/api/projects/{name}/job")
    def job(name: str, body: ProgramIn) -> dict:
        """What the browser needs to run Python or R itself, or the result if it can't run."""
        from blockcode.engine import browser_job

        project = load(name)
        target = target_ok(body.target)
        if target not in BROWSER_TARGETS:
            raise HTTPException(400, "Only Python and R run in the browser.")
        todo, stopped = browser_job(store, project, body.program, target)
        return {"job": todo.model_dump()} if todo else {"result": stopped.model_dump()}

    @app.post("/api/projects/{name}/finish")
    def finish(name: str, body: FinishIn) -> dict:
        """Turn what a run in the browser produced into a result (friendly errors, blocks)."""
        from blockcode.engine import finish as finish_run

        project = load(name)
        target = target_ok(body.target)
        if target not in BROWSER_TARGETS:
            raise HTTPException(400, "Only Python and R run in the browser.")
        return finish_run(project, body.program, target, body.raw).model_dump()

    @app.get("/api/projects/{name}/files/{path:path}")
    def data_file(name: str, path: str) -> FileResponse:
        """A project's data file (only the tables' CSVs), for runs in the browser."""
        project = load(name)
        table = next((t for t in project.tables if t.file == path), None)
        f = store.dir(project.name) / path if table else None
        if f is None or not f.is_file():
            raise HTTPException(404, "No such data file.")
        return FileResponse(f, media_type="text/csv")

    @app.post("/api/projects/{name}/parse")
    def parse(name: str, body: ParseIn) -> dict:
        from blockcode.parse import parse_code

        project = load(name)
        return parse_code(body.code, target_ok(body.lang), project.tables,
                          previous=body.previous).model_dump()

    @app.get("/api/projects/{name}/erd")
    def erd(name: str) -> dict:
        from blockcode.erd import infer_erd

        project = load(name)
        return infer_erd(project.tables, store.ensure_db(project.name)).model_dump()

    @app.post("/api/projects/{name}/export")
    def export(name: str, body: ProgramIn) -> Response:
        from blockcode.export import export_project

        project = load(name)
        project.program = body.program
        with TemporaryDirectory() as tmp:
            try:
                files = export_project(store, project, target_ok(body.target), Path(tmp))
            except ProjectError as exc:
                raise HTTPException(400, str(exc)) from exc
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for f in files:
                    z.write(f, f.relative_to(tmp).as_posix())
        fname = f"{project.name}-{body.target}.zip"
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    web = next((d for d in WEB_DIRS if (d / "index.html").is_file()), None)
    if web is not None:
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app


# Module-level app for ASGI hosts: Vercel (see [tool.vercel] in pyproject.toml) and
# `uvicorn blockcode.server:app`. `blockcode serve` builds its own with create_app().
app = create_app()
