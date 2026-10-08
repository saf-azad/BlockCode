import pandas as pd

courses = pd.read_csv("data/courses.csv", dtype_backend="numpy_nullable")

out = courses
out = out[out["title"].str.lower().str.contains("ic", regex=False) | out["dept"].str.lower().str.startswith("his")]
