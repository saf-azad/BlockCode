---
title: "BlockCode"
format: html
---

```{r}
#| label: setup
#| message: false
library(dplyr)
library(readr)
library(stringr)
courses <- read_csv("data/courses.csv", show_col_types = FALSE, col_types = "ccc")
```

```{r}
#| label: out
out <- courses |>
  filter(str_detect(tolower(title), fixed("ic")) | str_starts(tolower(dept), fixed("his")))
out
```
