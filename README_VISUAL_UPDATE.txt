AttendAI — Maroon Theme + Full-Screen Camera Update

This UI-only patch includes:
- Premium deep-maroon / red visual theme across the existing pages.
- Larger camera stage by default and a true Full screen / Exit full screen toggle.
- Randomized head-movement instructions drawn directly over each detected face rectangle.
- Subject selector on the live-attendance page (required by the subject-wise backend).
- Existing recognition activity and motion-only verification are preserved; the anti-spoof decision remains disabled as requested.

Install:
1. Stop Flask (Ctrl+C).
2. Keep a backup of the AttendAI project folder.
3. Extract this ZIP into C:\Users\Lenovo\Desktop\AttendAI and replace only the files it contains.
4. Run: python app.py
5. Open http://127.0.0.1:5000/attendance and press Ctrl+F5.
6. Select a subject, click Start camera, then click Full screen. Instructions appear on the face box.

Included files only: templates/attendance.html, static/css/style.css, static/js/app.js. No model, student profile, database or attendance records are included.
