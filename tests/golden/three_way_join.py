import pandas as pd

enrolments = pd.read_csv("data/enrolments.csv", dtype_backend="numpy_nullable")
students = pd.read_csv("data/students.csv", dtype_backend="numpy_nullable")
courses = pd.read_csv("data/courses.csv", dtype_backend="numpy_nullable")

out = enrolments
out = out.merge(students, on="student_id")
out = out.merge(courses, on="course_id")
out = out[out["year"] == 13]
out = out.groupby(["dept", "term"], as_index=False, dropna=False).agg(
    lowest=("grade", "min"),
)
