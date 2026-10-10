import pandas as pd

enrolments = pd.read_csv("data/enrolments.csv", dtype_backend="numpy_nullable")

out = enrolments
out = out.assign(half=out["grade"] / 2)
out = out.assign(id_ratio=out["student_id"] / 7)
out = out[out["half"] > 45]
out = out.sort_values(["half", "student_id"], ascending=[False, True], kind="stable")
out = out.head(20)
