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
courses <- read_csv("data/courses.csv", show_col_types = FALSE)
```

```{r}
#| label: out
out <- enrolments |>
  inner_join(courses, by = "course_id") |>
  filter(grade > 50) |>
  group_by(dept) |>
  summarise(avg_grade = mean(grade, na.rm = TRUE), n = n()) |>
  filter(n >= 10) |>
  arrange(desc(avg_grade)) |>
  slice_head(n = 5)
out
```
