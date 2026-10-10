import pandas as pd

enrolments = pd.read_csv("data/enrolments.csv", dtype_backend="numpy_nullable")
courses = pd.read_csv("data/courses.csv", dtype_backend="numpy_nullable")

out = enrolments
out = out.merge(courses, on="course_id")
out = out[out["grade"] > 50]
out = out.groupby("dept", as_index=False, dropna=False).agg(
    avg_grade=("grade", "mean"),
    n=("student_id", "size"),
)
out = out[out["n"] >= 10]
out = out.sort_values("avg_grade", ascending=False, kind="stable")
out = out.head(5)
