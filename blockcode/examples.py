"""Example programs for the school sample dataset (shown in the editor's Examples menu)."""

from blockcode import build as b
from blockcode.ir import Program

TITLES = {
    "department_grades": "Top departments by average grade",
    "s1_maths": "Maths grades in term S1",
    "year_counts": "Students in each year",
    "whole_table_summary": "Summary of every grade",
    "three_way_join": "Lowest Year 13 grade per department and term",
    "derived_percent": "Grades as a new column",
    "text_tests": "Courses by name",
}


def school():
    return {
        "department_grades": b.program(b.from_(
            "enrolments",
            b.join("courses", "course_id"),
            b.where(b.cmp(">", b.col("grade"), b.lit(50))),
            b.group(["dept"], b.agg("avg", "grade", "avg_grade"), b.agg("count", None, "n")),
            b.having(b.cmp(">=", b.col("n"), b.lit(10))),
            b.order(("avg_grade", True)),
            b.limit(5),
        )),
        "s1_maths": b.program(b.from_(
            "enrolments",
            b.join("courses", "course_id"),
            b.where(b.and_(b.cmp("=", b.col("term"), b.lit("S1")),
                           b.cmp("=", b.col("dept"), b.lit("Mathematics")))),
            b.select("student_id", "title", "grade"),
        )),
        "year_counts": b.program(b.from_(
            "students",
            b.group(["year"], b.agg("count", None, "students")),
            b.order("year"),
        )),
        "whole_table_summary": b.program(b.from_(
            "enrolments",
            b.group([], b.agg("avg", "grade", "avg_grade"), b.agg("count", "grade", "graded"),
                    b.agg("count", None, "rows"), b.agg("max", "grade", "best")),
        )),
        "three_way_join": b.program(b.from_(
            "enrolments",
            b.join("students", "student_id"),
            b.join("courses", "course_id"),
            b.where(b.cmp("=", b.col("year"), b.lit(13))),
            b.group(["dept", "term"], b.agg("min", "grade", "lowest")),
        )),
        "derived_percent": b.program(b.from_(
            "enrolments",
            b.derive("half", b.math("/", b.col("grade"), b.lit(2))),
            b.derive("id_ratio", b.math("/", b.col("student_id"), b.lit(7))),
            b.where(b.cmp(">", b.col("half"), b.lit(45))),
            b.order(("half", True), "student_id"),
            b.limit(20),
        )),
        "text_tests": b.program(b.from_(
            "courses",
            b.where(b.or_(b.text("contains", b.col("title"), "ic"),
                          b.text("starts", b.col("dept"), "his"))),
        )),
    }


def get(name: str) -> Program:
    return school()[name]
