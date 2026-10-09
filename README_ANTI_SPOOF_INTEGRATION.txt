AttendAI — MiniFASNet anti-spoofing integration patch

FILES IN THIS PATCH
- app.py: adds repeated-frame anti-spoof gating before the existing randomized head movement challenge and attendance write.
- src/anti_spoofing.py: corrected MiniFASNet preprocessing/inference. This model export already returns softmax probabilities; it does not softmax them again.
- static/js/app.js: amber while checking, red for probable print/replay attack, green only when both anti-spoof and motion challenge pass.

INSTALL
1. Stop Flask with Ctrl+C.
2. Make sure the project folder backup exists.
3. Extract this ZIP into C:\Users\Lenovo\Desktop\AttendAI and replace the included files.
4. Verify models\face_anti_spoofing.onnx exists.
5. Run: python app.py
6. Open http://127.0.0.1:5000/attendance and hard-refresh with Ctrl+F5.

GATING
MiniFASNet is evaluated across a rolling window of five consecutive frames. The current frame must have live probability >= 0.80, and at least 4 of the 5 recent frames must meet that threshold. It then requires the existing randomized head-turn, return-to-center and opposite-turn challenge. Attendance is never written while either check is pending.

LIMITATIONS
This is a basic presentation-attack deterrent, not a guarantee. Model thresholds must be validated using real consenting faces, printouts, phone screens, and replay videos under the actual camera/lighting conditions. A result should not be described as foolproof. If genuine users cannot pass, tune the threshold only after reviewing observed probabilities and attack test results. For a high-stakes deployment, use a validated PAD implementation and security evaluation.
