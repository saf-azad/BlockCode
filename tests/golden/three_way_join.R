---
title: "BlockCode"
format: html
---

```{r}
#| label: setup
#| message: false
library(dplyr)
library(readr)
enrolments <- read_csv("data/enrolments.csv", show_col_types = FALSE)
students <- read_csv("data/students.csv", show_col_types = FALSE)
courses <- read_csv("data/courses.csv", show_col_types = FALSE)
```

```{r}
#| label: out
out <- enrolments |>
  inner_join(students, by = "student_id") |>
  inner_join(courses, by = "course_id") |>
  filter(year == 13) |>
  group_by(dept, term) |>
  summarise(lowest = min(grade, na.rm = TRUE), .groups = "drop")
out
```
