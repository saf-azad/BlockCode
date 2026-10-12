"""Property tests over randomly built data programs on the school dataset:

* parse(generate(P, lang)) regenerates identical code in every language;
* SQL and pandas return the same table (a smaller sample, since each run starts Python).
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from blockcode import build as b
from blockcode.codegen import generate
from blockcode.engine import run
from blockcode.parse import parse_code
from tests.test_equivalence import compare

NUM = {"enrolments": ["student_id", "grade"], "students": ["year"], "courses": []}
TEXT = {"enrolments": ["course_id", "term"], "students": ["name"], "courses": ["title", "dept"]}
VALUES = {"term": ["S1", "S2"], "dept": ["Mathematics", "History", "Biology"],
          "course_id": ["MAT101", "BIO103"], "title": ["Algebra", "Poetry"],
          "name": ["Ava Khan", "Leo Smith"]}


@st.composite
def condition(draw, nums, texts, depth=0):
    kinds = ["num", "text", "empty", "inlist", "like"] + (["and", "or", "not"] if depth < 2 else [])
    kind = draw(st.sampled_from(kinds))
    if kind == "num":
        return b.cmp(draw(st.sampled_from(["=", "!=", "<", "<=", ">", ">="])),
                     b.col(draw(st.sampled_from(nums))), b.lit(draw(st.integers(0, 100))))
    if kind == "text":
        c = draw(st.sampled_from(texts))
        return b.cmp(draw(st.sampled_from(["=", "!="])), b.col(c),
                     b.lit(draw(st.sampled_from(VALUES[c]))))
    if kind == "empty":
        return b.isempty(b.col(draw(st.sampled_from(nums + texts))))
    if kind == "inlist":
        c = draw(st.sampled_from(texts))
        return b.inlist(b.col(c), draw(st.lists(st.sampled_from(VALUES[c]), min_size=1,
                                                max_size=2, unique=True)))
    if kind == "like":
        c = draw(st.sampled_from(texts))
        return b.text(draw(st.sampled_from(["contains", "starts", "ends"])), b.col(c),
                      draw(st.sampled_from(["a", "o", "s1", "ma"])))
    if kind == "not":
        return b.not_(draw(condition(nums, texts, depth + 1)))
    fn = b.and_ if kind == "and" else b.or_
    return fn(draw(condition(nums, texts, depth + 1)), draw(condition(nums, texts, depth + 1)))


@st.composite
def data_program(draw):
    steps = []
    nums, texts = list(NUM["enrolments"]), list(TEXT["enrolments"])
    for t in draw(st.lists(st.sampled_from(["courses", "students"]), max_size=2, unique=True)):
        steps.append(b.join(t, "course_id" if t == "courses" else "student_id",
                            draw(st.sampled_from(["inner", "left"]))))
        nums += NUM[t]
        texts += TEXT[t]
    if draw(st.booleans()):
        steps.append(b.derive("calc", b.math(draw(st.sampled_from(["+", "-", "*", "/"])),
                                             b.col(draw(st.sampled_from(nums))),
                                             b.lit(draw(st.integers(1, 9))))))
        nums.append("calc")
    for _ in range(draw(st.integers(0, 2))):
        steps.append(b.where(draw(condition(nums, texts))))
    cols = nums + texts
    if draw(st.booleans()):
        keys = draw(st.lists(st.sampled_from(texts), min_size=0, max_size=2, unique=True))
        if "calc" in nums:
            keys.append("calc")  # SQL drops a new column that grouping doesn't use
        aggs = [b.agg("count", None, "n")]
        # sum over an all-empty group is 0 in pandas/R but NULL in SQL (a documented limit), so
        # only sum columns that are never empty; the other functions agree either way
        sure = [c for c in nums if c in ("student_id", "year")] or ["student_id"]
        for i, f in enumerate(draw(st.lists(st.sampled_from(["avg", "sum", "min", "max",
                                                             "count"]), max_size=2))):
            col = draw(st.sampled_from(sure if f == "sum" else nums))
            aggs.append(b.agg(f, col, f"{f}_{i}"))
        steps.append(b.group(keys, *aggs))
        cols = keys + [a["as"] for a in aggs]
        if keys and draw(st.booleans()):
            steps.append(b.having(b.cmp(">", b.col("n"), b.lit(draw(st.integers(0, 50))))))
    group = next((s for s in steps if s.type == "group"), None)
    if draw(st.booleans()) and len(cols) > 1:
        cols = draw(st.lists(st.sampled_from(cols), min_size=1, max_size=3, unique=True))
        if group is not None:
            # SQL can't keep a summary it doesn't show, and it lists summaries in SELECT order,
            # so keep them all, in their own order, after the keys
            names = [a["as"] for a in group.field("aggs")]
            cols = [c for c in cols if c not in names] + names
            if "calc" in group.field("by") and "calc" not in cols:
                cols.insert(0, "calc")  # a grouping-only new column has no name in SQL
        if "calc" in nums and "calc" not in cols and not any(s.type == "group" for s in steps):
            cols.append("calc")  # SQL drops a new column that Select doesn't keep
        canonical = (group.field("by") + [a["as"] for a in group.field("aggs")]
                     if group is not None else None)
        if cols != canonical:  # a Select that changes nothing has no SQL of its own
            steps.append(b.select(*cols))
    if draw(st.booleans()):
        # order by every column so the order is fully fixed (ties would make it ambiguous)
        steps.append(b.order(*[(c, draw(st.booleans())) for c in cols]))
        if draw(st.booleans()):
            steps.append(b.limit(draw(st.integers(0, 20))))
    return b.program(b.from_("enrolments", *steps))


SETTINGS = dict(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


@settings(max_examples=150, **SETTINGS)
@given(program=data_program())
def test_round_trip_all_languages(store, program):
    tables = {t.name: t for t in store.load("school").tables}
    want = {lang: generate(program, tables, lang).code for lang in ("sql", "python", "r")}
    for lang in ("sql", "python", "r"):
        result = parse_code(want[lang], lang, tables)
        assert result.ok, (lang, want[lang], result.diagnostics)
        for other in ("sql", "python", "r"):
            assert generate(result.program, tables, other).code == want[other], (lang, other)


@settings(max_examples=12, **SETTINGS)
@given(program=data_program())
def test_sql_and_pandas_agree(store, program):
    project = store.load("school")
    sql = run(store, project, program, "sql")
    if not sql.ok:  # e.g. a column clash after two joins; the validator explains those
        return
    compare(store, "school", program)
