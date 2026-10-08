SELECT year,
       COUNT(*) AS students
FROM students
GROUP BY year
ORDER BY year;
