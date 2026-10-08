"""Run generated R with Rscript when it is installed. Tables come back as CSV."""

from __future__ import annotations

import base64
import csv
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from blockcode.codegen.emitter import Generated
from blockcode.errors import friendly
from blockcode.run import MAX_ROWS, RunError, RunResult, TableResult, clip_output

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
.bc_args <- commandArgs(trailingOnly = TRUE)
.bc_out <- .bc_args[1]; .bc_names <- strsplit(.bc_args[2], ",")[[1]]
.bc_src <- .bc_args[3]
# Every plot page goes to plot001.png, plot002.png, ... on a real PNG device, so plots show
# however they are drawn: a ggplot at the top level, print() inside a loop, or base graphics.
# (Hooking print.ggplot instead misses ggplot2 4, whose plots are S7 objects.)
.bc_png <- file.path(.bc_out, "plot%%03d.png")
tryCatch({
  if (requireNamespace("ragg", quietly = TRUE)) {
    ragg::agg_png(.bc_png, width = 6, height = 4, units = "in", res = 110)
  } else {
    png(.bc_png, width = 6, height = 4, units = "in", res = 110)
  }
}, error = function(e) {
  pdf(NULL)
  writeLines(conditionMessage(e), file.path(.bc_out, "nodevice.txt"))
})
.bc_pages <- 0
setHook("grid.newpage", function() .bc_pages <<- .bc_pages + 1, "append")
setHook("plot.new", function() .bc_pages <<- .bc_pages + 1, "append")
.bc_exprs <- parse(.bc_src, keep.source = TRUE)
.bc_err <- NULL
for (.bc_e in seq_along(.bc_exprs)) {
  .bc_line <- getSrcLocation(.bc_exprs[.bc_e], "line")
  .bc_last <- getSrcLocation(.bc_exprs[.bc_e], "line", first = FALSE)
  .bc_before <- .bc_pages
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
  if (!.bc_ok) {
    # a plot that failed half way leaves a blank page behind: drop it
    .bc_pages <- .bc_before
    break
  }
}
invisible(dev.off())
# some devices write a blank file even when nothing was drawn; say how many pages are real
writeLines(as.character(.bc_pages), file.path(.bc_out, "pages.txt"))
for (.bc_n in .bc_names) {
  if (exists(.bc_n, envir = globalenv()) && is.data.frame(get(.bc_n, envir = globalenv()))) {
    .bc_df <- as.data.frame(get(.bc_n, envir = globalenv()))
    write.csv(head(.bc_df, %(max_rows)d), file.path(.bc_out, paste0("table_", .bc_n, ".csv")),
              row.names = FALSE, na = "")
    writeLines(as.character(nrow(.bc_df)), file.path(.bc_out, paste0("rows_", .bc_n, ".txt")))
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


def _draws_plots(gen: Generated) -> bool:
    return any("ggplot(" in ln.text for ln in gen.lines)


def _cell(v: str):
    if v == "":
        return None
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    if v in ("TRUE", "FALSE"):
        return v == "TRUE"
    return v


def run_r(gen: Generated, project_dir: Path, names: list[str],
          timeout: float = TIMEOUT_S) -> RunResult:
    result = RunResult(target="r", ok=True)
    exe = rscript()
    if exe is None:
        result.ok = False
        result.error = RunError(kind="NoR", message="R isn't installed on this computer, so "
                                "R code can't run here. You can still read and export it.")
        return result
    code, nums = strip_quarto(gen)
    with tempfile.TemporaryDirectory(prefix="blockcode-r-") as tmp:
        tmpd = Path(tmp)
        (tmpd / "program.R").write_text(code)
        (tmpd / "h.R").write_text(HARNESS)
        try:
            proc = subprocess.run([exe, "--vanilla", str(tmpd / "h.R"), str(tmpd),
                                   ",".join(names), str(tmpd / "program.R")], cwd=project_dir, capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            result.ok = False
            result.error = RunError(kind="Timeout", message=friendly("Timeout", "", "r"))
            return result
        result.stdout = clip_output(proc.stdout)
        err = tmpd / "error.txt"
        if err.exists():
            lines = err.read_text().splitlines()
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
                with open(t, newline="") as f:
                    rows = list(csv.reader(f))
                total = int((tmpd / f"rows_{n}.txt").read_text().strip() or 0)
                result.tables.append(TableResult(name=n, columns=rows[0] if rows else [],
                                                 rows=[[_cell(v) for v in r] for r in rows[1:]],
                                                 total_rows=total))
        pages_txt = tmpd / "pages.txt"
        pages = int(pages_txt.read_text().strip() or 0) if pages_txt.exists() else 0
        for png in sorted(tmpd.glob("plot*.png"), key=lambda p: int(re.sub(r"\D", "", p.stem))):
            if int(re.sub(r"\D", "", png.stem)) <= pages:
                result.plots.append(base64.b64encode(png.read_bytes()).decode())
        nodev = tmpd / "nodevice.txt"
        if nodev.exists() and result.error is None and _draws_plots(gen):
            result.ok = False
            result.error = RunError(
                kind="NoPlotDevice", message="R ran, but it couldn't save the plots as pictures "
                "on this computer. Installing the ragg package (install.packages(\"ragg\")) "
                "usually fixes this.", detail=nodev.read_text().strip())
    return result
