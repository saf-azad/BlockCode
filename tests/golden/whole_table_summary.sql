SELECT AVG(grade) AS avg_grade,
       COUNT(grade) AS graded,
       COUNT(*) AS rows,
       MAX(grade) AS best
FROM enrolments;
