"""Learners don't type code exactly the way BlockCode writes it."""

from blockcode.codegen import generate
from blockcode.parse import parse_code


def tables(store):
    return {t.name: t for t in store.load("school").tables}


def types(result):
    return [b.type for b in result.program.walk()]


def sql(store, code):
    r = parse_code(code, "sql", tables(store))
    assert r.ok, r.diagnostics
    return r


def test_sql_lowercase_one_line(store):
    r = sql(store, "select * from students where year >= 12 order by name limit 10")
    assert types(r) == ["from", "where", "cmp", "col", "lit", "order", "limit"]
    assert generate(r.program, tables(store), "python").code.endswith("out = out.head(10)\n")


def test_sql_alias_on_join_distinct(store):
    r = sql(store, "SELECT DISTINCT c.dept FROM enrolments e JOIN courses c "
                   "ON e.course_id = c.course_id WHERE e.grade > 90")
    t = types(r)
    assert t[:2] == ["from", "join"] and "group" in t
    g = [b for b in r.program.walk() if b.type == "group"][0]
    assert g.field("by") == ["dept"]


def test_sql_aggregate_without_alias_and_left_join(store):
    r = sql(store, "SELECT term, COUNT(*), AVG(grade) AS avg FROM enrolments "
                   "LEFT JOIN students USING (student_id) GROUP BY term")
    g = [b for b in r.program.walk() if b.type == "group"][0]
    assert [a["as"] for a in g.field("aggs")] == ["n", "avg"]
    assert [b for b in r.program.walk() if b.type == "join"][0].field("how") == "left"


def test_sql_where_and_on_one_line_is_one_block(store):
    r = sql(store, "SELECT * FROM enrolments WHERE grade > 50 AND term = 'S1'")
    assert types(r).count("where") == 1
    r = sql(store, "SELECT *\nFROM enrolments\nWHERE grade > 50\n  AND term = 'S1'")
    assert types(r).count("where") == 2


def test_sql_unsupported_and_typos(store):
    r = parse_code("SELECT * FROM (SELECT * FROM students)", "sql", tables(store))
    assert not r.ok and "Not a block yet" in r.diagnostics[0].message
    r = parse_code("SELECT name FROM students WHERE year > 12\nAND", "sql", tables(store))
    assert not r.ok and r.diagnostics[0].severity == "error"
    r = parse_code("SELECT UPPER(name) AS n FROM students", "sql", tables(store))
    assert not r.ok
    r = parse_code("SELECT *\nFROM students\nWHERE name LIKE 'A_n%'", "sql", tables(store))
    assert not r.ok and r.diagnostics[0].line == 3


def py(store, code):
    r = parse_code(code, "python", tables(store))
    assert r.ok, r.diagnostics
    return r


def test_python_method_chain(store):
    r = py(store, """
import pandas as pd
enrolments = pd.read_csv("data/enrolments.csv")
courses = pd.read_csv("data/courses.csv")
top = (enrolments.merge(courses, on="course_id")
       .query("grade > 50 and term == 'S1'")
       .groupby("dept", as_index=False)
       .agg(avg_grade=("grade", "mean"), n=("grade", "size"))
       .sort_values("avg_grade", ascending=False)
       .head(3))
print(top)
""")
    assert [b.type for b in r.program.blocks] == ["from", "print"]
    frm = r.program.blocks[0]
    assert frm.field("name") == "top"
    assert [s.type for s in frm.stack("steps")] == ["join", "where", "group", "order", "limit"]
    assert not [d for d in r.diagnostics if d.severity != "info"]


def test_python_loc_attribute_columns_and_having(store):
    r = py(store, """
import pandas as pd
df = pd.read_csv("data/enrolments.csv")
df = df.loc[df.grade.notna() & (df.term == "S2")]
df = df.groupby("course_id", as_index=False).agg(n=("grade", "count"))
df = df[df.n > 40]
""")
    steps = r.program.blocks[0].stack("steps")
    assert [s.type for s in steps] == ["where", "group", "having"]
    sql_code = generate(r.program, tables(store), "sql").code
    assert "WHERE NOT (grade IS NULL) AND term = 'S2'" in sql_code
    assert "HAVING COUNT(grade) > 40" in sql_code


def test_python_unknown_code_becomes_raw(store):
    r = py(store, """
import json
x = 1
data = json.dumps({"a": x})
print(data)
""")
    kinds = [b.type for b in r.program.blocks]
    assert kinds == ["raw", "setvar", "raw", "print"]
    assert r.program.blocks[0].field("code") == "import json"
    assert any(d.severity == "info" and d.line == 2 for d in r.diagnostics)


def test_python_syntax_error_keeps_blocks(store):
    r = parse_code("out = enrolments[\n", "python", tables(store))
    assert not r.ok and r.program is None
    assert r.diagnostics[0].line in (1, 2)


def rr(store, code):
    r = parse_code(code, "r", tables(store))
    assert r.ok, r.diagnostics
    return r


def test_r_magrittr_and_count(store):
    r = rr(store, """
library(tidyverse)
enrolments <- read_csv("data/enrolments.csv")
by_term <- enrolments %>%
  filter(!is.na(grade), grade >= 40) %>%
  count(term) %>%
  arrange(desc(n))
by_term
""")
    steps = r.program.blocks[0].stack("steps")
    assert [s.type for s in steps] == ["where", "where", "group", "order"]
    assert generate(r.program, tables(store), "sql").code.splitlines()[0] == "SELECT term,"


def test_r_nested_verbs_and_loop(store):
    r = rr(store, """
students <- read.csv("data/students.csv")
old <- filter(students, year == 13)
total <- 0
for (i in seq_len(nrow(old))) {
  row <- old[i, ]
  if (startsWith(row$name, "A")) {
    total <- total + 1
  }
}
cat("Names starting with A:", total, "\\n")
""")
    kinds = [b.type for b in r.program.blocks]
    assert kinds == ["from", "setvar", "foreach", "print"]
    body = r.program.blocks[2].stack("body")
    assert body[0].type == "if" and body[0].stack("body")[0].type == "changevar"


def test_r_unknown_becomes_raw_and_typo(store):
    r = rr(store, "x <- 1\nf <- function(a) a + 1\nprint(x)")
    assert [b.type for b in r.program.blocks] == ["setvar", "raw", "print"]
    bad = parse_code("x <- (1 + \n", "r", tables(store))
    assert not bad.ok


def test_r_quarto_chunks_only(store):
    r = rr(store, """---
title: "Test"
---

Some text with x <- nonsense(

```{r}
students <- read_csv("data/students.csv")
out <- students |> slice_head(n = 2)
```
""")
    assert [s.type for s in r.program.blocks[0].stack("steps")] == ["limit"]
    assert r.spans[r.program.blocks[0].stack("steps")[0].id] == [9]
