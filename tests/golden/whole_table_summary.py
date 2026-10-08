import pandas as pd

enrolments = pd.read_csv("data/enrolments.csv", dtype_backend="numpy_nullable")

out = enrolments
out = pd.DataFrame({
    "avg_grade": [out["grade"].mean()],
    "graded": [out["grade"].count()],
    "rows": [len(out)],
    "best": [out["grade"].max()],
})
