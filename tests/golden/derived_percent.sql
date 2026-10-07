SELECT *,
       grade / 2 AS half,
       student_id / 7.0 AS id_ratio
FROM enrolments
WHERE grade / 2 > 45
ORDER BY half DESC, student_id
LIMIT 20;
