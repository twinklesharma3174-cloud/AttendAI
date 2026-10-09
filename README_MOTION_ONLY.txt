AttendAI — Motion-only update (anti-spoof temporarily disabled)

This patch modifies only:
  app.py
  static/js/app.js

It removes MiniFASNet anti-spoof inference and keeps the randomized YuNet
landmark challenge: front-facing calibration, turn toward the requested side,
return to center, then turn toward the opposite side. Attendance is recorded
only after this movement challenge is complete, and one daily record per
student is preserved by the existing attendance system.

Install:
1. Stop Flask with Ctrl+C.
2. Keep your current project backup.
3. Extract this ZIP into C:\Users\Lenovo\Desktop\AttendAI and replace included files.
4. Run: python app.py
5. Open http://127.0.0.1:5000/attendance and press Ctrl+F5.

Note: this intentionally disables anti-spoof model detection. Movement-only
verification can be fooled by suitable replay videos and is not strong
presentation-attack protection. The face_anti_spoofing.onnx model and
src/anti_spoofing.py can remain on disk unused; they are not imported here.
