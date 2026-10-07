"""Regenerate the school sample dataset in blockcode/data/sample (deterministic)."""

import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "blockcode" / "data" / "sample"
rng = random.Random(2026)

FIRST = ["Ava", "Ben", "Chloe", "Dev", "Ella", "Finn", "Grace", "Hugo", "Isla", "Jack", "Kiara",
         "Leo", "Maya", "Noah", "Olivia", "Priya", "Quinn", "Ruby", "Sam", "Tara", "Umar", "Vera",
         "Will", "Xena", "Yusuf", "Zoe"]
LAST = ["Ahmed", "Brown", "Chen", "Davies", "Evans", "Fischer", "Garcia", "Hughes", "Ito",
        "Jones", "Khan", "Lopez", "Murphy", "Nguyen", "Okafor", "Patel", "Quinn", "Rossi",
        "Smith", "Taylor"]
DEPTS = {  # dept: (course code prefix, mean grade)
    "Mathematics": ("MAT", 74.0), "Physics": ("PHY", 70.5), "English": ("ENG", 68.0),
    "History": ("HIS", 65.5), "Biology": ("BIO", 63.0), "Chemistry": ("CHE", 60.5),
}
TITLES = {
    "Mathematics": ["Algebra", "Calculus", "Statistics", "Geometry"],
    "Physics": ["Mechanics", "Waves", "Electricity", "Astronomy"],
    "English": ["Poetry", "Drama", "Novels", "Writing"],
    "History": ["Ancient World", "Medieval Europe", "Modern History", "World Wars"],
    "Biology": ["Cells", "Ecology", "Genetics", "Human Body"],
    "Chemistry": ["Atoms", "Reactions", "Organic", "Lab Skills"],
}

students = [(i, f"{rng.choice(FIRST)} {rng.choice(LAST)}", rng.choice([10, 11, 12, 13]))
            for i in range(1, 481)]
courses = []
for dept, (code, _) in DEPTS.items():
    for k, title in enumerate(TITLES[dept], start=1):
        courses.append((f"{code}{100 + k}", title, dept))

enrolments = []
mean = {c[0]: DEPTS[c[2]][1] for c in courses}
while len(enrolments) < 2310:
    s = rng.choice(students)
    c = rng.choice(courses)
    term = rng.choice(["S1", "S2"])
    g = max(5.0, min(100.0, rng.gauss(mean[c[0]] + (s[2] - 11.5) * 1.5, 12)))
    enrolments.append([s[0], c[0], round(g, 1), term])
for i in rng.sample(range(len(enrolments)), 8):
    enrolments[i][2] = ""

OUT.mkdir(parents=True, exist_ok=True)
for name, header, rows in [
    ("students", ["student_id", "name", "year"], students),
    ("courses", ["course_id", "title", "dept"], courses),
    ("enrolments", ["student_id", "course_id", "grade", "term"], enrolments),
]:
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
print("wrote", OUT)
