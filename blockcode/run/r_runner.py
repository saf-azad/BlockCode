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
from blockcode.run import MAX_ROWS, RunError, RunResult, TableResult

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
pdf(NULL)
.bc_plot <- 0
print.ggplot <- function(x, ...) {
  .bc_plot <<- .bc_plot + 1
  ggplot2::ggsave(file.path(.bc_out, sprintf("plot%%d.png", .bc_plot)), x, width = 6,
                  height = 4, dpi = 110)
  invisible(x)
}
.bc_exprs <- parse(.bc_src, keep.source = TRUE)
.bc_err <- NULL
for (.bc_e in seq_along(.bc_exprs)) {
  .bc_line <- getSrcLocation(.bc_exprs[.bc_e], "line")
  .bc_ok <- tryCatch({
    .bc_v <- withVisible(eval(.bc_exprs[[.bc_e]], envir = globalenv()))
    if (.bc_v$visible) print(.bc_v$value)
    TRUE
  }, error = function(e) {
    writeLines(c(as.character(.bc_line), conditionMessage(e)), file.path(.bc_out, "error.txt"))
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
  }
}
''' % {"max_rows": MAX_ROWS}


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
        result.stdout = proc.stdout
        err = tmpd / "error.txt"
        if err.exists():
            lines = err.read_text().splitlines()
            local = int(lines[0]) if lines and lines[0].isdigit() else None
            line = nums[local - 1] if local and local <= len(nums) else None
            msg = "\n".join(lines[1:])
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
        for png in sorted(tmpd.glob("plot*.png"), key=lambda p: int(re.sub(r"\D", "", p.stem))):
            result.plots.append(base64.b64encode(png.read_bytes()).decode())
    return result
