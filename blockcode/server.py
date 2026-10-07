"""FastAPI server: JSON API under /api and the built web app at /."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from blockcode import __version__
from blockcode.codegen import TARGETS, generate
from blockcode.ir import Program, Project
from blockcode.project_io import ProjectError, ProjectStore
from blockcode.registry import SPECS, STEP_ORDER

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
MAX_UPLOAD = 20 * 1024 * 1024


class ProgramIn(BaseModel):
    program: Program
    target: str = "sql"


class ParseIn(BaseModel):
    code: str
    lang: str
    previous: Program | None = None


class NewProject(BaseModel):
    name: str
    title: str = ""
    sample: bool = True


def create_app(projects_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="BlockCode", version=__version__)
    store = ProjectStore(Path(projects_dir or "projects").resolve())
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
        if not store.exists(name) and name == "school":
            return store.create("school", "Department grades")
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
        out = generate(body.program, project.tables, target_ok(body.target))
        return out.model_dump()

    @app.post("/api/projects/{name}/generate-all")
    def gen_all(name: str, body: ProgramIn) -> dict:
        project = load(name)
        return {t: generate(body.program, project.tables, t).model_dump() for t in TARGETS}

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

    @app.post("/api/projects/{name}/parse")
    def parse(name: str, body: ParseIn) -> dict:
        from blockcode.parse import parse_code

        project = load(name)
        return parse_code(body.code, target_ok(body.lang), project.tables,
                          previous=body.previous).model_dump()

    @app.get("/api/projects/{name}/erd")
    def erd(name: str) -> dict:
        from blockcode.erd import infer_erd

        return infer_erd(load(name).tables).model_dump()

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

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
