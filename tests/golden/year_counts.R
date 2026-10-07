---
title: "BlockCode"
format: html
---

```{r}
#| label: setup
#| message: false
library(dplyr)
library(readr)
students <- read_csv("data/students.csv", show_col_types = FALSE)
```

```{r}
#| label: out
out <- students |>
  group_by(year) |>
  summarise(students = n()) |>
  arrange(year)
out
```
