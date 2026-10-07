SELECT student_id,
       title,
       grade
FROM enrolments
JOIN courses USING (course_id)
WHERE term = 'S1' AND dept = 'Mathematics';
