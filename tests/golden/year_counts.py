import pandas as pd

students = pd.read_csv("data/students.csv", dtype_backend="numpy_nullable")

out = students
out = out.groupby("year", as_index=False, dropna=False).agg(
    students=("student_id", "size"),
)
out = out.sort_values("year", kind="stable")
