---
title: "BlockCode"
format: html
---

```{r}
#| label: setup
#| message: false
library(dplyr)
library(readr)
enrolments <- read_csv("data/enrolments.csv", show_col_types = FALSE, col_types = "?c?c")
courses <- read_csv("data/courses.csv", show_col_types = FALSE, col_types = "ccc")
```

```{r}
#| label: out
out <- enrolments |>
  inner_join(courses, by = "course_id") |>
  filter(term == "S1" & dept == "Mathematics") |>
  select(student_id, title, grade)
out
```
