SELECT dept,
       term,
       MIN(grade) AS lowest
FROM enrolments
JOIN students USING (student_id)
JOIN courses USING (course_id)
WHERE year = 13
GROUP BY dept, term;
