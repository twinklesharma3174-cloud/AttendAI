AttendAI — Subject-wise Attendance Update

What is added:
- Faculty can create subjects with unique codes at /subjects.
- Faculty must select a subject before starting Live Attendance.
- Browser recognition requests are linked to the selected subject.
- SQLite stores attendance uniquely by student + subject + date.
- A student's attendance in one subject does not block attendance in another subject on the same day.
- A subject/date session is created as soon as the camera starts sending frames, even if no student has been marked yet; this supports absence calculation for that subject session.
- Reports can be filtered by subject and date range, and CSV/PDF exports include the subject.
- Existing date-only attendance data is kept under an inactive "General / Legacy" subject during SQLite migration.
- The anti-spoof model decision is DISABLED per user request. Randomized head movement (left/right, center, opposite side) remains required before marking attendance.
- Because anti-spoof is disabled, photos/replay videos may still fool the system; this is not proxy-proof.

Install:
1. Stop Flask (Ctrl+C).
2. Backup the current AttendAI project folder.
3. Extract the ZIP into C:\Users\Lenovo\Desktop\AttendAI and replace only the files it contains.
4. Run: python app.py
5. Open http://127.0.0.1:5000/subjects and create each subject (e.g., DSA, DBMS, Applied Mathematics).
6. Open Live Attendance, choose a subject, and start the camera.
7. Open Reports and filter by a subject.

Important design constraint:
This prototype records at most one attendance session per subject per calendar date. If you need multiple lectures of the same subject in one day or separate sections, a future version should use explicit lecture-session IDs and faculty-controlled session opening/closing.

The patch does not include or overwrite models/, data/students/, attendance/ or your existing attendai.db.
