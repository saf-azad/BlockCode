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
```

```{r}
#| label: out
out <- enrolments |>
  mutate(half = grade / 2) |>
  mutate(id_ratio = student_id / 7) |>
  filter(half > 45) |>
  arrange(desc(half), student_id) |>
  slice_head(n = 20)
out
```
