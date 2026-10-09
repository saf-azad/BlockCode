# BlockCode: end-to-end build plan (v4 design)

## Context
Learners struggle to write valid SQL, Python or R, and to see how the three relate. In BlockCode they drop in CSVs, snap colour-coded blocks into a stack, and read the matching code live in **SQL, Python (pandas) or R (dplyr/Quarto)**. The blocks don't belong to any one language: switching language rewrites the code panel and leaves the workspace as it is. **New requirement: the link also runs the other way.** Typing or pasting code in the Code tab rebuilds the blocks.

The design source is the v4 mockup (`BlockCode v4.dc.html` in the uploaded zip). The repo `saf-azad/BlockCode` currently holds only a LICENSE. We work on branch `claude/dazzling-fermi-k9njli`.

Decisions so far:
- **Editor:** a custom React stack editor replaces Blockly.
- **R:** codegen and export are always available. R runs only when `Rscript` is found.
- **In scope:** the Plot tab with 4 charts, the hover isometric animations, and the ERD view.
- **Engine:** a local FastAPI server with a shared Python engine that serves both the web UI and the CLI.

## Architecture
```
            ┌──────────── blocks → IR ─────────────┐
React stack editor ⇄ Program IR ⇄ Python core engine
            └── code → IR (parse) ◄── editable Code tab
core: plan.py ─► codegen.sql | codegen.pandas | codegen.r (+ codegen.python for imperative)
      parse.sql (sqlglot) | parse.python (ast) | parse.r (hand-written dplyr subset)
      validate(target) · run(target) · export(target) · source maps both directions
```
- **Program IR** (pydantic): a tree of `Block{id, type, fields, inputs, body, next}`. Data blocks reduce to one relational plan: `Source → Join* → Where* → Group/Agg → Having → Derive/Select → Order → Limit`. Every backend walks this same plan.
- **Language-neutral data blocks:** From, Join, Where, Group by (+ count/sum/avg/min/max), Having, Select, New column, Order by, Limit. **Expressions** are round pills: column, literal, compare, and/or/not, maths, is empty, in list, contains/starts/ends.
- **Python/R-only blocks** (dashed outline): Set var, Print, For each, If/else, While, Plot (bar/line/scatter/hist). A pipeline can sit inside For each. If any of these blocks is present, SQL is turned off and each one gets a "no SQL equivalent" problem. In SQL mode, plot blocks detach from the stack and sit greyed out (as in v4).
- **Source maps:** each emitted line is tagged with block ids (block → lines highlight), and each parsed node keeps its span (lines → block).

### Code → blocks (two-way editing)
- The Code tab is an editable **CodeMirror 6** editor. After a 500 ms pause in typing, it calls `POST /api/parse?lang=` with the text. The server returns `{program, spans, diagnostics}`.
- **Parsers recognise BlockCode's own subset**, and both directions are tested against each other: `parse(generate(P)) == P` for every example and in property tests.
  - SQL: **sqlglot** (SQLite dialect) gives an AST, which becomes a plan, which becomes blocks. It handles SELECT/FROM/JOIN … USING/ON, WHERE, GROUP BY + aggregates, HAVING, ORDER BY, LIMIT, CASE-less expressions and aliases.
  - Python: the built-in `ast` module. It recognises the pandas idioms we emit (`read_csv`, `merge`, boolean masks, `query`, `groupby().agg()`, `sort_values`, `head`, `assign`, `[[cols]]`, method chains or reassignment), plus `for`/`if`/`while`/`print`/assignment and `df.plot.*`/`plt.show()`.
  - R: a small hand-written tokenizer and recursive-descent parser for the dplyr subset: `<-`, `|>`/`%>%`, `read_csv`, `left_join/inner_join`, `filter`, `group_by`, `summarise`, `mutate`, `select`, `arrange(desc())`, `slice_head`, `for`, `if`, `print/paste`, `ggplot + geom_*`. Quarto chunks are read from inside ```` ```{r} ```` fences, and YAML and `#|` lines are ignored.
- **Partial or unsupported code:**
  - A syntax error leaves the blocks as they are and puts a red squiggle with a friendly message on the code.
  - Code that parses but uses constructs we don't support keeps the blocks we could recognise. The rest goes into an opaque, dashed **"Raw code"** block (Python/R only, and it turns SQL off), so nothing the learner typed is lost. A Problems entry says "this line can't become a block yet".
- **Keeping things stable:** parsed blocks are matched to the existing blocks (by type and position in the stack) so their ids, hover state and plot settings survive edits. The learner's own text stays in the editor while they type. It is replaced with tidied generated code only when they press **Tidy** or switch language.
- Typing SQL and then switching to Python shows the same blocks as pandas code. This is the core teaching moment, and it now works in both directions.

## Repo layout
```
pyproject.toml          # uv; pydantic fastapi uvicorn typer pandas matplotlib sqlglot python-multipart pytest hypothesis
blockcode/
  ir.py  registry.py  blocks/{data_blocks,python_blocks,plot_blocks}.py
  plan.py               # IR ⇄ relational plan + clause-structure checks
  codegen/{emitter,sql,pandas,python,r}.py   # emitter → SourceMap; r.py emits plain .R and Quarto .qmd
  parse/{sql,python,r,match}.py              # code → IR; match.py keeps block ids stable
  validate.py  errors.py                     # per-target diagnostics, friendly messages
  data_io.py            # CSV ingest: types, empty counts, SQLite load, schema
  erd.py                # infers links from shared column names, PK/FK guesses, cardinality
  run/{sql_runner,python_runner,r_runner}.py # sqlite3 | subprocess 5 s | Rscript if found; trace → block_id
  project_io.py  cli.py  server.py
  data/sample/{students,courses,enrolments}.csv   # matches v4: 480 / 24 / 2,310 rows, 8 empty grades
web/  (Vite + React + TS)
  src/theme.ts          # PAL / THEMES per language, ported from v4; button set "c" (soft)
  src/stack/            # Stack, Block, Pill, CBlock (For each / If), palette, dnd-kit snapping, clause auto-order
  src/code/             # CodeMirror editor, highlighting, per-line block tags, parse round-trip
  src/panels/           # Output table/stdout, Plot, Problems
  src/sidebar/          # Tables (types, empty counts), CSV dropzone overlay, ERD (crow/Chen/UML)
  src/explainers/       # isometric scenes + rAF tick ported from v4 `scenes()`/`tick()`
  src/triBar.tsx        # bottom bar: hovered block in SQL ⇄ pandas ⇄ dplyr
  src/api.ts  src/linking.ts  src/App.tsx
examples/  tests/
```

## Milestones (each one ends green and pushed)
1. **M0 Scaffold:** uv project, Vite React app, `blockcode serve` serves the API and the built web app, plus CI (pytest, tsc, vitest).
2. **M1 Data engine (headless):** IR, registry, plan, SQL and pandas codegen with source maps, CSV ingest, SQL and Python runners, sample data. Running `blockcode run --target sql|python` on an example gives the same table.
3. **M2 R target:** dplyr codegen (.R and Quarto .qmd as in v4) and an R runner that runs when `Rscript` is found. Golden codegen tests.
4. **M3 Imperative and plot blocks:** codegen.python and R loops/if/print, pipelines inside For each, Plot blocks (matplotlib → PNG, ggplot2 → PNG), SQL-incompatibility validation, var-before-set, tracebacks mapped to blocks.
5. **M4 Code → blocks:** the parse/sql, parse/python and parse/r modules, Raw-code fallback, id matching, and round-trip property tests (hypothesis generates random valid programs).
6. **M5 Editor shell:** v4 layout, per-language theme, palette (Blocks / Conditions / Python & R), stack with drag, snap, clause auto-order and × remove, column dropdowns, read-only Code tab with SQL/Python/R toggle, the tri-language bar, and hover line highlighting.
7. **M6 Two-way editing:** editable CodeMirror, debounced parse → blocks, squiggles, Tidy button, Raw-code blocks.
8. **M7 CSV drop and tables:** drop overlay ("Columns we found"), upload, sidebar tables with types and empty counts, new source block and column dropdowns.
9. **M8 Run & debug:** Run uses the current language. Output tab (table or stdout), Plot tab, Problems tab with badge, and two-way error ↔ block linking ("Show me the block →").
10. **M9 Explainers and ERD:** an ERD panel with crow's foot, Chen and UML notations, and a hover isometric animation for **every** block type. Each animation must show what the block really does to the rows. Where the v4 design has no scene, we design a new one: new column, select, if/else, while, repeat, set/change var and raw code.
   - **Join** is redone so it matches rows by key. Key cubes are coloured by value. With an inner join, matching pairs slide together and rows with no match drop away. With a left join, every left row stays and unmatched rows get an empty (hollow) partner cube.
   - Each scene is checked against the engine. A test runs the block on a tiny table and asserts the row counts and matches the scene animates (for example, inner join 3 + 3 → 2 rows, left join → 3 rows).
11. **M10 Projects & export:** `*.blockcode.json` save/load, export .sql, .py or .qmd/.R plus data from both the UI and the CLI, examples, friendly-error polish.
- **Stretch:** functions, subqueries, a compare mode that runs all three targets side by side.

## Risks and semantics
- **Nulls:** NULL and NaN behave differently. "is empty" generates `IS NULL`, `isna()` or `is.na()`, and the equivalence tests use data with nulls.
- **Row order:** without ORDER BY, results are compared as sets.
- **Types:** type inference must match across targets, and dates stay text.
- **Joins:** SQL `JOIN` is an inner join, so the generated dplyr uses `inner_join` rather than the `left_join` shown in the v4 mockup. Otherwise the three targets would return different rows.
- **Round trip:** only BlockCode's subset round-trips. Anything else becomes Raw code, which is clearly marked. Hand-written SQL with features we don't support (subqueries, window functions) gets a clear "not a block yet" message rather than a silent rewrite.
- **Generated code:** it must match what learners would write by hand, so the parsers accept common variants (reassignment or method chain, `%>%` or `|>`, `==` or `=`).

## Verification
- **Equivalence tests:** every data example runs as SQL and pandas on the same CSVs and the result tables must match (order-insensitive unless sorted, nulls included). R joins the comparison when Rscript is available.
- **Round-trip tests:** for each example and random program, `parse(gen(P, lang)) ≅ P` for all three languages, and `gen(parse(code))` is stable.
- **Golden and unit tests:** golden codegen tests per block per target, plus tests for the validator, runners, CSV ingest, ERD inference, the API (TestClient) and the CLI (CliRunner).
- **Standalone exports:** exported files run on their own with `python out.py`, `sqlite3 db.sqlite < out.sql` (or the Python sqlite3 module), and `Rscript out.R` where R is present.
- **UI end to end** with Playwright on the preinstalled Chromium:
  1. Drop a CSV and build From → Where → Group by.
  2. Toggle SQL / Python / R: the code changes and the blocks don't.
  3. Type `LIMIT 3` in the SQL tab and check a Limit block appears. Paste a pandas snippet and check the stack rebuilds.
  4. Run in SQL and Python and check the tables match.
  5. Add For each and check SQL is struck through and a Problems entry appears.
  6. Cause a NameError and click it to check the right block is outlined.
  7. Add a plot and check it detaches in SQL and renders in Python.
  8. Export all three.

## Status

**MVP for a public launch (blank start).** The editor now opens empty: no sample tables, no
preloaded program, no Examples menu. Each visitor's tables and blocks are kept in their own
browser and the server is stateless (`/api/tables`, `/api/generate-all`, `/api/parse`, `/api/erd`,
`/api/run`, `/api/export`), so it runs the same on one machine, in Docker, or on Vercel. Uploaded
CSVs are tidied so SQL, pandas and R agree (`blockcode/data_io.py`, tested in
`tests/test_awkward_csvs.py`), and learners' code runs with a clean environment and limits
(`blockcode/run/sandbox.py`).

All milestones M0–M10 are built and tested. Each one was pushed as its own commit on
`claude/dazzling-fermi-k9njli`.

| Area | Where | Tests |
|---|---|---|
| Engine: IR, plan, SQL / pandas / dplyr codegen with source maps | `blockcode/` | `tests/test_codegen.py`, `tests/test_golden.py` |
| SQL ≡ pandas ≡ R result tables (null cases too) | `blockcode/run/` | `tests/test_equivalence.py`, `tests/test_properties.py` |
| Code → blocks (SQL, Python, R) | `blockcode/parse/` | `tests/test_roundtrip.py`, `tests/test_parse_handwritten.py`, property tests |
| Python/R-only blocks, plots, error → block | `blockcode/codegen/python.py`, `r.py` | `tests/test_imperative.py` |
| CSV ingest, projects, export, ERD, API, CLI | `blockcode/` | `tests/test_server.py`, `tests/test_cli.py`, `tests/test_export.py` |
| Hover animations tell the truth | `web/src/explainers/` | `tests/test_explainers.py`, `scenes.test.ts` |
| Editor (v4 design) | `web/src/` | `web/e2e/editor.spec.ts` (Playwright) |

Open `/?gallery` to see every hover animation at once.

Known limits in v1:
- A new column that a later Group by or Select drops has no SQL of its own. The validator warns
  about this.
- `NOT IN` on a column with empty values and `SUM` over only-empty groups follow SQL in SQL, but
  pandas and R return different results.
- LIKE patterns with `%` or `_` in the middle, subqueries and window functions are not blocks yet.
