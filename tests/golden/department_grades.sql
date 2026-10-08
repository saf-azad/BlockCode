SELECT dept,
       AVG(grade) AS avg_grade,
       COUNT(*) AS n
FROM enrolments
JOIN courses USING (course_id)
WHERE grade > 50
GROUP BY dept
HAVING COUNT(*) >= 10
ORDER BY avg_grade DESC
LIMIT 5;
