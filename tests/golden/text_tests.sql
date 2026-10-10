SELECT *
FROM courses
WHERE title LIKE '%ic%' ESCAPE '\' OR dept LIKE 'his%' ESCAPE '\';
