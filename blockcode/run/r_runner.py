"""Run generated R with Rscript when it is installed. Tables come back as CSV."""

from __future__ import annotations

import base64
import csv
import re
import shutil
import tempfile
from pathlib import Path

from blockcode.codegen.emitter import Generated
from blockcode.errors import friendly
from blockcode.run import MAX_ROWS, RunError, RunResult, TableResult
from blockcode.run.python_runner import TOO_MUCH
from blockcode.run.sandbox import MAX_PLOTS, child_env, run_captured

TIMEOUT_S = 20.0


def rscript() -> str | None:
    return shutil.which("Rscript")


def strip_quarto(gen: Generated) -> tuple[str, list[int]]:
    """Keep only the R inside ```{r} chunks; return the code and its original line numbers."""
    out, nums, inside = [], [], False
    is_quarto = any(ln.text.startswith("```") for ln in gen.lines)
    for ln in gen.lines:
        t = ln.text
        if t.startswith("```{r"):
            inside = True
            continue
        if t.startswith("```"):
            inside = False
            continue
        if (inside or not is_quarto) and not t.startswith("#|"):
            out.append(t)
            nums.append(ln.n)
    return "\n".join(out) + "\n", nums


HARNESS = r'''
# Compare and sort text by byte value, the way SQLite and pandas do, so the three targets agree
# on filters like name > "M", on min()/max() of text, and on arrange(); without this R would
# use the machine's locale collation and could order text differently.
invisible(suppressWarnings(Sys.setlocale("LC_COLLATE", "C")))
.bc_args <- commandArgs(trailingOnly = TRUE)
.bc_out <- .bc_args[1]; .bc_names <- strsplit(.bc_args[2], ",")[[1]]
.bc_src <- .bc_args[3]
pdf(NULL)
.bc_plot <- 0
print.ggplot <- function(x, ...) {
  .bc_plot <<- .bc_plot + 1
  ggplot2::ggsave(file.path(.bc_out, sprintf("plot%%d.png", .bc_plot)), x, width = 6,
                  height = 4, dpi = 110)
  invisible(x)
}
.bc_exprs <- tryCatch(parse(.bc_src, keep.source = TRUE), error = function(e) {
  writeLines(c("1", "1", "", conditionMessage(e)), file.path(.bc_out, "error.txt"))
  NULL
})
if (is.null(.bc_exprs)) quit(save = "no", status = 1)
.bc_err <- NULL
for (.bc_e in seq_along(.bc_exprs)) {
  .bc_line <- getSrcLocation(.bc_exprs[.bc_e], "line")
  .bc_last <- getSrcLocation(.bc_exprs[.bc_e], "line", first = FALSE)
  .bc_ok <- tryCatch({
    .bc_x <- .bc_exprs[[.bc_e]]
    .bc_v <- withVisible(eval(.bc_x, envir = globalenv()))
    # a bare result name (Quarto shows the table) is already returned as a table
    .bc_shown <- is.name(.bc_x) && as.character(.bc_x) %%in%% .bc_names
    if (.bc_v$visible && !.bc_shown) print(.bc_v$value)
    TRUE
  }, error = function(e) {
    cl <- conditionCall(e)
    cl <- if (is.null(cl)) "" else paste(deparse(cl), collapse = " ")
    writeLines(c(as.character(.bc_line), as.character(.bc_last), cl, conditionMessage(e)),
               file.path(.bc_out, "error.txt"))
    FALSE
  })
  if (!.bc_ok) break
}
for (.bc_n in .bc_names) {
  if (exists(.bc_n, envir = globalenv()) && is.data.frame(get(.bc_n, envir = globalenv()))) {
    .bc_df <- as.data.frame(get(.bc_n, envir = globalenv()))
    write.csv(head(.bc_df, %(max_rows)d), file.path(.bc_out, paste0("table_", .bc_n, ".csv")),
              row.names = FALSE, na = "")
    writeLines(as.character(nrow(.bc_df)), file.path(.bc_out, paste0("rows_", .bc_n, ".txt")))
    writeLines(vapply(.bc_df, function(x) class(x)[1], ""),
               file.path(.bc_out, paste0("types_", .bc_n, ".txt")))
  }
}
''' % {"max_rows": MAX_ROWS}


def _error_line(code: list[str], first: int | None, last: int | None, call: str,
                msg: str) -> int | None:
    """R only tells us which top-level expression failed. Narrow it to the line that holds the
    failing call, or the missing object's name."""
    if first is None:
        return None
    span = range(first, (last or first) + 1)
    needles = []
    m = re.search(r"object '([^']+)' not found", msg)
    if m:
        needles.append(rf"(?<![\w.$]){re.escape(m.group(1))}(?![\w.])")
    if call:
        needles.append(re.escape(call.split("(")[0]) + r"\(")
    for pat in needles:
        for n in span:
            if n <= len(code) and re.search(pat, code[n - 1]):
                return n
    return first


def _cell(v: str, kind: str = ""):
    """A value from R's CSV, typed by its column's R class (text stays text, so "007" in a
    character column isn't turned into 7)."""
    if v == "":
        return None
    if kind in ("character", "factor", "Date", "POSIXct", "difftime", "hms"):
        return v
    if kind == "logical" or v in ("TRUE", "FALSE"):
        return v == "TRUE" if v in ("TRUE", "FALSE") else v
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def run_r(gen: Generated, project_dir: Path, names: list[str],
          timeout: float = TIMEOUT_S) -> RunResult:
    result = RunResult(target="r", ok=True)
    exe = rscript()
    if exe is None:
        result.ok = False
        result.error = RunError(kind="NoR", message="R isn't installed where BlockCode is "
                                "running, so R code can't run here. You can still read it and "
                                "export it to run in RStudio.")
        return result
    code, nums = strip_quarto(gen)
    # result names name the files the harness writes, so only plain R names are passed on
    names = [n for n in names if re.fullmatch(r"[A-Za-z.][A-Za-z0-9._]*", n)]
    with tempfile.TemporaryDirectory(prefix="blockcode-r-") as tmp:
        tmpd = Path(tmp)
        (tmpd / "program.R").write_text(code, encoding="utf-8")
        (tmpd / "h.R").write_text(HARNESS)
        ran = run_captured([exe, "--vanilla", str(tmpd / "h.R"), str(tmpd), ",".join(names),
                            str(tmpd / "program.R")], cwd=project_dir, timeout=timeout,
                           env=child_env(), scratch=tmpd)
        result.stdout = ran.stdout
        if ran.timed_out or ran.too_much:
            result.ok = False
            result.error = (RunError(kind="Timeout", message=friendly("Timeout", "", "r"))
                            if ran.timed_out else
                            RunError(kind="TooMuchOutput", message=TOO_MUCH))
            return result
        err = tmpd / "error.txt"
        if err.exists():
            lines = err.read_text(encoding="utf-8", errors="replace").splitlines()
            first = int(lines[0]) if lines and lines[0].isdigit() else None
            last = int(lines[1]) if len(lines) > 1 and lines[1].isdigit() else first
            call, msg = (lines[2] if len(lines) > 2 else ""), "\n".join(lines[3:])
            local = _error_line(code.splitlines(), first, last, call, msg)
            line = nums[local - 1] if local and local <= len(nums) else None
            blocks = gen.blocks_at(line) if line else []
            result.ok = False
            result.error = RunError(kind="RError", message=friendly("RError", msg, "r"),
                                    detail=msg, line=line,
                                    block_id=blocks[-1] if blocks else None)
        for n in names:
            t = tmpd / f"table_{n}.csv"
            if t.exists():
                with open(t, newline="", encoding="utf-8") as f:
                    rows = list(csv.reader(f))
                total = int((tmpd / f"rows_{n}.txt").read_text().strip() or 0)
                kinds_file = tmpd / f"types_{n}.txt"
                kinds = kinds_file.read_text().splitlines() if kinds_file.exists() else []
                kind = lambda i: kinds[i] if i < len(kinds) else ""  # noqa: E731
                header = rows[0] if rows else []
                width = len(header)
                # a one-column row that is a single empty value is a blank line, which
                # csv.reader returns as [], so pad every short row back to the header width
                result.tables.append(TableResult(
                    name=n, columns=header,
                    rows=[[_cell(v, kind(i)) for i, v in enumerate(r + [""] * (width - len(r)))]
                          for r in rows[1:]],
                    total_rows=total))
        pngs = sorted(tmpd.glob("plot*.png"), key=lambda p: int(re.sub(r"\D", "", p.stem)))
        for png in pngs[:MAX_PLOTS]:
            result.plots.append(base64.b64encode(png.read_bytes()).decode())
    return result
