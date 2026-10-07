import pandas as pd

enrolments = pd.read_csv("data/enrolments.csv", dtype_backend="numpy_nullable")
courses = pd.read_csv("data/courses.csv", dtype_backend="numpy_nullable")

out = enrolments
out = out.merge(courses, on="course_id")
out = out[(out["term"] == "S1") & (out["dept"] == "Mathematics")]
out = out[["student_id", "title", "grade"]]
