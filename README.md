# BlockCode

Scratch-style blocks for learning data work. Drop in a CSV, snap blocks into a stack, and read the
matching code live in **SQL**, **Python (pandas)** or **R (dplyr / Quarto)**. The blocks have no
language of their own: switching language rewrites the code panel and leaves the workspace alone.
It works the other way too: type or paste code in the Code tab and the blocks rebuild.

Every visitor starts with a blank workspace: no sample data, no templates. They add their own CSV
(or paste cells from a spreadsheet) and build from there.

See [`docs/PLAN.md`](docs/PLAN.md) for the build plan and `docs/design/` for the v4 design mockup.

## How it works

- **The browser keeps the work.** A visitor's tables, blocks and title are saved in their own
  browser (IndexedDB), so a refresh or a return visit picks up where they left off. **New** clears
  it. Private windows still work, but forget everything when closed.
- **The server keeps nothing.** It reads a CSV's columns when it is added, writes code, and runs
  code. To run or export, the browser sends the CSVs along (gzipped). They are tidied into a
  temporary folder, used, and deleted. Visitors never see each other's data, and any number of
  server instances can serve the same visitor.
- **Messy CSVs are tidied on the way in**, so SQL, pandas and R read the same table: other
  encodings (Windows-1252, Latin-1, UTF-16), semicolon / tab / `|` separators, blank, repeated or
  padded headers, `NA` / `N/A` / `null` as empty, `1,234` and decimal commas as numbers, and short
  or long rows. The "Columns we found" card lists what was changed. Excel files, empty files and
  binary files are turned away with a reason.

## Quick start

```bash
uv sync                      # Python engine + server
(cd web && npm install && npm run build)
uv run blockcode serve       # http://127.0.0.1:8000
```

## Development

```bash
uv run pytest                # engine, API, CLI and messy-CSV tests
(cd web && npm run dev)      # Vite dev server, proxies /api to :8000
(cd web && npm test)         # frontend unit tests
(cd web && npm run build && npm run e2e)   # browser tests (Playwright) against the real engine
```

R is optional: R code is always generated and exported, and runs when `Rscript` (with dplyr,
readr, stringr and ggplot2) is installed. Without it, the R tab shows and exports code, and the
Run button explains why it can't run there.

The `blockcode` CLI (`new`, `import-csv`, `code`, `run`, `export`) still works on projects in a
folder on disk; `blockcode new` adds the school sample unless you pass `--empty`.

## Deploying

### Docker: everything, including R

The `Dockerfile` builds one image with the editor, the engine and R, so all three languages run.
It listens on `$PORT` (default 8000), which suits Render, Railway, Fly.io, Cloud Run or any VPS.

```bash
docker build -t blockcode .
docker run -p 8000:8000 blockcode      # http://localhost:8000
```

### Vercel: SQL and Python

`pyproject.toml` points Vercel at the FastAPI app (`[tool.vercel] entrypoint =
"blockcode.server:app"`), and its build script compiles the editor into `public/`, which Vercel
serves from its CDN, so importing the repository in Vercel and deploying is meant to be all it takes.
Vercel has no R, so the R tab shows and exports code but can't run it. Vercel limits a request to
4.5 MB, which is several CSVs of a few MB each once gzipped.

## Limits and safety

- A CSV can be up to 10 MB. Results show the first 200 rows. Python stops after 10 seconds, R
  after 20. A run returns at most 12 plots and 100,000 characters of printed output.
- Code typed in the Python or R tab can include lines that aren't blocks (they become "Raw code"
  blocks), so **visitors can run any Python or R on the server**. Each run gets a clean environment
  (none of the server's variables), CPU-time and file-size limits, and capped output; in the Docker
  image it also runs as a user that can't change the app. Don't give the deployment secrets it
  doesn't need. For a large public audience, also put the host behind rate limiting.
