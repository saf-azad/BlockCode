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

## Where programs run

In the web app, **Python and R run in your browser**, in WebAssembly builds of each:
[Pyodide](https://pyodide.org) for Python and [webR](https://docs.r-wasm.org/webr/) for R.
Nothing needs installing, and the server never runs learners' Python or R. The first run
downloads Python or R, plus the packages the program uses (pandas and matplotlib; dplyr,
readr, stringr and ggplot2), which takes a little while. The browser caches them, and the
download starts as soon as you pick the Python or R tab. After that, runs are near instant.
SQL runs on the server, in SQLite.

The server still prepares each run (the code, a small harness around it, the CSVs it reads)
and explains the outcome (friendly errors that point at their block), so a run in the browser
gives the same results as one on the server. If Python or R can't start in a browser (offline,
or a firewall blocks the download), runs fall back to the server, which needs its own Python
(always there) and R (`Rscript` with dplyr, readr, stringr and ggplot2; plots are saved with
`ragg` if installed, else `png()`).

| Environment variable | Default |
| --- | --- |
| `BLOCKCODE_RUN_IN` | `browser`; `server` runs Python and R on the server instead |
| `BLOCKCODE_PYODIDE_URL` | `https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs` |
| `BLOCKCODE_WEBR_URL` | `https://webr.r-wasm.org/v0.6.0/webr.mjs` |
| `BLOCKCODE_WEBR_REPO` | `https://repo.r-wasm.org/` (where R packages come from) |

To self-host, point these at your own copies of the Pyodide and webR releases. The CLI
(`blockcode run`) always runs on this machine.

In the editor, Ctrl+Enter (⌘+Enter) runs the program. After the first run, the results follow
the blocks: each edit re-runs the program once its code has no problems.

## Deploying to Vercel

`pyproject.toml` points Vercel at the FastAPI app (`[tool.vercel] entrypoint =
"blockcode.server:app"`). The build script compiles the web editor into `public/`, which Vercel
serves from its CDN. On Vercel, projects live in `/tmp`, so uploads and saved programs last only as
long as a function instance; set `BLOCKCODE_PROJECTS_DIR` to change where they go. Python and R run in
learners' browsers, so they work on Vercel too.
