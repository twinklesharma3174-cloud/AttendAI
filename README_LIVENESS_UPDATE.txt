AttendAI — Basic photo-proxy deterrent update

WHAT THIS UPDATE DOES
- Adds a live head-movement challenge before daily attendance is marked.
- Challenge sequence: look straight and hold still, turn your head to one side, return to center, then turn to the other side.
- Attendance is not written while the liveness status is pending.
- Face overlay is amber during the liveness check, green after verification, and red for unknown faces.
- Student activity is logged once per student in the browser session.

INSTALL
1. Stop the Flask server with Ctrl+C.
2. Make a backup of your current AttendAI folder.
3. Extract the archive into the existing AttendAI folder and allow replacement of files.
4. Run: python app.py
5. Open http://127.0.0.1:5000/attendance and click Start camera.

TEST
- First look directly at the camera and hold still while it calibrates.
- Follow each instruction shown in Recognition activity.
- A registered face should have an amber box during verification and turn green only after verification.
- A still printout or stationary phone image should remain unverified and must not be marked present.
- Then test a real consenting enrolled person to ensure the camera and challenge work with normal movement.

LIMITATIONS
This is a basic challenge-response deterrent for static photographs, not a certified presentation-attack detection system. It may be fooled by replay videos, a deliberately manipulated image/photo, or other sophisticated attacks. A real deployment should use a validated PAD/liveness model, secure enrollment/admin controls, audit logs, and an independent security evaluation. The liveness state is stored in memory and is designed for a single local Flask process.
