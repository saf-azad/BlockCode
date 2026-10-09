"""Run generated Python in a subprocess with a timeout, capturing stdout, tables and plots.

The learner's code runs exactly as exported, from the project directory so ``data/x.csv``
resolves. A small harness around it saves figures instead of opening windows, reports the
final value of each pipeline variable, and turns a traceback into a line number.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from blockcode.codegen.emitter import Generated
from blockcode.errors import friendly
from blockcode.run import MAX_ROWS, RunError, RunResult, TableResult
from blockcode.run.sandbox import MAX_PLOTS, child_env, run_captured

TIMEOUT_S = 10.0
TOO_MUCH = ("Your program printed so much that it was stopped. Print fewer rows, or add a "
            "Limit block.")

HARNESS = r'''
import base64, io, json, sys, traceback
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as _plt

_code_path, _out_path, _names = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
_figs = []

def _show(*args, **kwargs):
    for num in _plt.get_fignums():
        if len(_figs) >= %(max_plots)d:
            break
        buf = io.BytesIO()
        _plt.figure(num).savefig(buf, format="png", dpi=110, bbox_inches="tight")
        _figs.append(base64.b64encode(buf.getvalue()).decode())
    _plt.close("all")

_plt.show = _show
_ns = {"__name__": "__main__"}
_err = None
try:
    with open(_code_path, encoding="utf-8") as f:
        _src = f.read()
    exec(compile(_src, "program.py", "exec"), _ns)
except SyntaxError as e:
    _err = {"kind": "SyntaxError", "detail": str(e.msg), "line": e.lineno}
except BaseException as e:
    _line = None
    for fr in traceback.extract_tb(e.__traceback__):
        if fr.filename == "program.py":
            _line = fr.lineno
    _detail = str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)
    _err = {"kind": type(e).__name__, "detail": _detail, "line": _line}
_show()

def _table(name, df):
    import pandas as pd
    df = df.reset_index(drop=True)
    head = df.head(%(max_rows)d).astype(object)
    rows = [[None if (not isinstance(v, (list, tuple)) and pd.isna(v)) else
             (v.item() if hasattr(v, "item") else v) for v in row]
            for row in head.itertuples(index=False, name=None)]
    return {"name": name, "columns": [str(c) for c in df.columns], "rows": rows,
            "total_rows": len(df)}

_tables = []
try:
    import pandas as pd
    for _n in _names:
        _v = _ns.get(_n)
        if isinstance(_v, pd.DataFrame):
            _tables.append(_table(_n, _v))
except BaseException as e:
    if _err is None:
        _err = {"kind": type(e).__name__, "detail": str(e), "line": None}
with open(_out_path, "w", encoding="utf-8") as f:
    json.dump({"error": _err, "tables": _tables, "plots": _figs}, f, default=str)
''' % {"max_rows": MAX_ROWS, "max_plots": MAX_PLOTS}


def run_python(gen: Generated, project_dir: Path, names: list[str],
               timeout: float = TIMEOUT_S) -> RunResult:
    result = RunResult(target="python", ok=True)
    with tempfile.TemporaryDirectory(prefix="blockcode-") as tmp:
        tmpd = Path(tmp)
        code_path, out_path, harness = tmpd / "program.py", tmpd / "result.json", tmpd / "h.py"
        code_path.write_text(gen.code, encoding="utf-8")
        harness.write_text(HARNESS, encoding="utf-8")
        ran = run_captured(
            [sys.executable, "-X", "utf8", str(harness), str(code_path), str(out_path),
             json.dumps(names)], cwd=project_dir, timeout=timeout, env=_env(), scratch=tmpd)
        result.stdout = ran.stdout
        if ran.timed_out:
            result.ok = False
            result.error = RunError(kind="Timeout", message=friendly("Timeout", "", "python"),
                                    detail=f"Stopped after {timeout:g} seconds.")
            return result
        if ran.too_much:
            result.ok = False
            result.error = RunError(kind="TooMuchOutput", message=TOO_MUCH)
            return result
        if not out_path.exists():
            result.ok = False
            result.error = RunError(kind="Crash", message="Python stopped unexpectedly.",
                                    detail=ran.stderr[-2000:])
            return result
        data = json.loads(out_path.read_text(encoding="utf-8"))
    result.tables = [TableResult(**t) for t in data["tables"]]
    result.plots = data["plots"]
    err = data["error"]
    if err:
        result.ok = False
        line = err.get("line")
        blocks = gen.blocks_at(line) if line else []
        result.error = RunError(kind=err["kind"],
                                message=friendly(err["kind"], err["detail"], "python"),
                                detail=f"{err['kind']}: {err['detail']}", line=line,
                                block_id=blocks[-1] if blocks else None)
    return result


def _env() -> dict:
    import os

    return child_env(
        # the child imports pandas and matplotlib from wherever this server found them
        PYTHONPATH=os.pathsep.join(p for p in sys.path if p),
        MPLBACKEND="Agg",
        # matplotlib caches fonts in its config dir; it must be writable (read-only $HOME on
        # Vercel)
        MPLCONFIGDIR=os.path.join(tempfile.gettempdir(), "blockcode-mpl"),
    )
