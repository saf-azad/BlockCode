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
```
