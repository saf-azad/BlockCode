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
```

```{r}
#| label: out
out <- enrolments |>
  summarise(
    avg_grade = mean(grade, na.rm = TRUE),
    graded = sum(!is.na(grade)),
    rows = n(),
    best = max(grade, na.rm = TRUE)
  )
out
```
