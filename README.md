# BlockCode

Scratch-style blocks for learning data work. Drop in a CSV, snap blocks into a stack, and read the
matching code live in **SQL**, **Python (pandas)** or **R (dplyr / Quarto)**. The blocks have no
language of their own: switching language rewrites the code panel and leaves the workspace alone.
It works the other way too: type or paste code in the Code tab and the blocks rebuild.

See [`docs/PLAN.md`](docs/PLAN.md) for the build plan and `docs/design/` for the v4 design mockup.

## Quick start

```bash
uv sync                      # Python engine + server
(cd web && npm install && npm run build)
uv run blockcode serve       # http://127.0.0.1:8000
```

## Development

```bash
uv run pytest                # engine, API and CLI tests
(cd web && npm run dev)      # Vite dev server, proxies /api to :8000
(cd web && npm test)         # frontend unit tests
(cd web && npm run build && npm run e2e)   # browser tests (Playwright) against the real engine
```

R is optional: R code is always generated and exported, and runs when `Rscript` (with dplyr,
readr, stringr and ggplot2) is installed.

## Deploying to Vercel

`pyproject.toml` points Vercel at the FastAPI app (`[tool.vercel] entrypoint =
"blockcode.server:app"`). The build script compiles the web editor into `public/`, which Vercel
serves from its CDN. On Vercel, projects live in `/tmp`, so uploads and saved programs last only as
long as a function instance; set `BLOCKCODE_PROJECTS_DIR` to change where they go. R runs only
where `Rscript` is installed, so on Vercel the R tab can show and export code but can't run it.
