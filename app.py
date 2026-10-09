import base64
import csv
import os
import re
import random
import time
import hmac
import secrets
import ssl
import smtplib
import sqlite3
from statistics import median
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from email.message import EmailMessage
from xml.sax.saxutils import escape as html_escape

import cv2
import numpy as np
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from src.attendance import AttendanceSystem
from src.database import (
    deactivate_student, get_attendance_rows, get_session_dates, get_setting,
    get_student_metadata, import_legacy_attendance, init_db,
    insert_attendance_once, record_session, record_subject_session, set_setting, sync_student_profile, update_student_email,
    create_subject, get_subject, get_subjects, get_subject_session_rows,
)

app = Flask(__name__)

def load_session_secret():
    """Use an environment secret or create a persistent local random key."""
    configured = os.environ.get("ATTENDAI_SECRET_KEY")
    if configured:
        return configured
    secret_path = os.path.join(app.root_path, ".attendai_session_key")
    try:
        if os.path.isfile(secret_path):
            with open(secret_path, "r", encoding="utf-8") as file:
                existing = file.read().strip()
            if len(existing) >= 32:
                return existing
        value = secrets.token_urlsafe(48)
        with open(secret_path, "w", encoding="utf-8") as file:
            file.write(value)
        return value
    except OSError:
        # Keep localhost usable if the folder is read-only; sessions then reset on restart.
        return secrets.token_urlsafe(48)

app.secret_key = load_session_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

# Load the existing recognition engine and enrolled students once.
# Anti-spoof model checks are intentionally disabled per user request.
# Attendance still requires the randomized left/center/right head-movement challenge.
attendance_system = AttendanceSystem()
# In-memory randomized liveness states, keyed by browser session and student ID.
# This is suitable for a single-machine hackathon demo, not a multi-worker deployment.
liveness_sessions = {}
LIVENESS_STATE_TTL_SECONDS = 600
CALIBRATION_FRAMES = 5
TURN_THRESHOLD = 0.095
CENTER_THRESHOLD = 0.055
REQUIRED_STABLE_FRAMES = 2

def face_yaw_signal(face):
    """Estimate relative head yaw using YuNet's eye and nose landmarks.

    YuNet row columns 4..9 contain the two eye centers and nose tip.
    The nose offset is normalized by eye distance, reducing sensitivity to
    face size and ordinary left/right movement within the camera frame.
    """
    try:
        eye_a = np.asarray(face[4:6], dtype=float)
        eye_b = np.asarray(face[6:8], dtype=float)
        nose = np.asarray(face[8:10], dtype=float)
        eye_distance = float(np.linalg.norm(eye_b - eye_a))
        if eye_distance < 1.0:
            return None
        eye_mid_x = (eye_a[0] + eye_b[0]) / 2.0
        return float((nose[0] - eye_mid_x) / eye_distance)
    except (ValueError, TypeError, IndexError):
        return None

def fresh_liveness_state(now):
    return {
        "phase": "calibrating",
        "samples": [],
        "baseline": None,
        "first_sign": 0,
        "first_target_sign": random.choice([-1, 1]),
        "stable_frames": 0,
        "updated_at": now,
    }

def advance_liveness(client_id, student_id, face):
    """Require a live, two-direction head movement before marking attendance.

    Challenge: establish a steady front-facing baseline, turn to one side,
    return to center, then turn to the opposite side.
    """
    now = time.time()

    # Clean old browser states to keep this local demo from growing indefinitely.
    for old_client in list(liveness_sessions.keys()):
        student_states = liveness_sessions[old_client]
        for old_student in list(student_states.keys()):
            if now - student_states[old_student].get("updated_at", now) > LIVENESS_STATE_TTL_SECONDS:
                student_states.pop(old_student, None)
        if not student_states:
            liveness_sessions.pop(old_client, None)

    per_client = liveness_sessions.setdefault(client_id, {})
    state = per_client.get(student_id)
    if state is None or (now - state.get("updated_at", now) > 60 and state.get("phase") != "verified"):
        state = fresh_liveness_state(now)
        per_client[student_id] = state
    state["updated_at"] = now

    signal = face_yaw_signal(face)
    if signal is None:
        return {"phase": state["phase"], "message": "Keep your face visible to the camera.", "verified": False}

    if state["phase"] == "verified":
        return {"phase": "verified", "message": "Liveness verified", "verified": True}

    if state["phase"] == "calibrating":
        samples = state["samples"]
        samples.append(signal)
        if len(samples) < CALIBRATION_FRAMES:
            return {"phase": "calibrating", "message": "Look straight at the camera and hold still.", "verified": False}

        if max(samples) - min(samples) > 0.16:
            state["samples"] = [signal]
            return {"phase": "calibrating", "message": "Hold still and look straight at the camera.", "verified": False}

        state["baseline"] = float(median(samples))
        state["samples"] = []
        state["phase"] = "turn_first"
        state["stable_frames"] = 0
        side = "left" if state["first_target_sign"] < 0 else "right"
        return {"phase": "turn_first", "message": f"Turn your head toward the {side} side of the screen.", "verified": False}

    delta = signal - state["baseline"]

    if state["phase"] == "turn_first":
        target_sign = state["first_target_sign"]
        target_reached = delta * target_sign >= TURN_THRESHOLD
        if target_reached:
            state["stable_frames"] += 1
            if state["stable_frames"] >= REQUIRED_STABLE_FRAMES:
                state["first_sign"] = target_sign
                state["phase"] = "return_center"
                state["stable_frames"] = 0
                return {"phase": "return_center", "message": "Good. Return your head to the center.", "verified": False}
        else:
            state["stable_frames"] = 0
        side = "left" if target_sign < 0 else "right"
        return {"phase": "turn_first", "message": f"Turn your head toward the {side} side of the screen.", "verified": False}

    if state["phase"] == "return_center":
        if abs(delta) <= CENTER_THRESHOLD:
            state["stable_frames"] += 1
            if state["stable_frames"] >= REQUIRED_STABLE_FRAMES:
                state["phase"] = "turn_other"
                state["stable_frames"] = 0
                return {"phase": "turn_other", "message": "Now turn your head to the other side.", "verified": False}
        else:
            state["stable_frames"] = 0
        return {"phase": "return_center", "message": "Return your head to the center.", "verified": False}

    if state["phase"] == "turn_other":
        opposite_sign = -state["first_sign"]
        opposite_side = delta * opposite_sign >= TURN_THRESHOLD
        if opposite_side:
            state["stable_frames"] += 1
            if state["stable_frames"] >= REQUIRED_STABLE_FRAMES:
                state["phase"] = "verified"
                state["stable_frames"] = 0
                return {"phase": "verified", "message": "Liveness verified", "verified": True}
        else:
            state["stable_frames"] = 0
        side = "left" if opposite_sign < 0 else "right"
        return {"phase": "turn_other", "message": f"Now turn your head toward the {side} side of the screen.", "verified": False}

    return {"phase": state["phase"], "message": "Follow the live camera instructions.", "verified": False}



DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "attendai.db")


def today_string():
    return date.today().strftime("%Y-%m-%d")


def read_attendance_file(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as file:
            return list(csv.DictReader(file))
    except (OSError, csv.Error):
        app.logger.exception("Could not read legacy attendance file: %s", path)
        return []


def read_all_attendance(start_date=None, end_date=None, subject_id=None):
    return get_attendance_rows(start_date, end_date, DB_PATH, subject_id=subject_id)


def get_today_rows(subject_id=None):
    return read_all_attendance(today_string(), today_string(), subject_id=subject_id)


def sync_legacy_data():
    """Create the SQLite registry and import existing NPZ profiles/CSV records once.

    NPZ files remain the source for biometric embeddings. SQLite becomes the
    authoritative source for student metadata, sessions, attendance and settings.
    """
    init_db(DB_PATH)

    # Sync currently enrolled face templates without reactivating deleted students.
    for student_id, record in attendance_system.students.items():
        profile_path = os.path.join(attendance_system.students_dir, f"{student_id}.npz")
        try:
            enrollment_date = datetime.fromtimestamp(os.path.getmtime(profile_path)).strftime("%Y-%m-%d")
        except OSError:
            enrollment_date = today_string()
        sync_student_profile(student_id, record["name"], enrollment_date, db_path=DB_PATH)

    # Import only legacy daily CSV files. New subject-specific CSV mirrors are
    # generated by this version and SQLite remains their authoritative source.
    folder = attendance_system.attendance_dir
    if os.path.isdir(folder):
        for filename in sorted(os.listdir(folder)):
            if not re.fullmatch(r"attendance_\d{4}-\d{2}-\d{2}\.csv", filename):
                continue
            fallback_date = filename[len("attendance_"):-len(".csv")]
            for row in read_attendance_file(os.path.join(folder, filename)):
                import_legacy_attendance(row, fallback_date, DB_PATH)


def decode_image(data_url):
    if not data_url or not isinstance(data_url, str):
        return None
    encoded = data_url.split(",", 1)[1] if "," in data_url else data_url
    image_bytes = base64.b64decode(encoded, validate=True)
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(array, cv2.IMREAD_COLOR)


def append_attendance_csv(row):
    """Mirror a subject attendance row to a separate CSV without mixing subjects."""
    os.makedirs(attendance_system.attendance_dir, exist_ok=True)
    code = re.sub(r"[^A-Za-z0-9_-]+", "_", str(row.get("Subject Code", "LEGACY"))).upper() or "SUBJECT"
    path = os.path.join(
        attendance_system.attendance_dir,
        f"attendance_subject_{code}_{row['Date']}.csv",
    )
    existing_rows = read_attendance_file(path)
    if any(
        str(item.get("Student ID", "")) == row["Student ID"]
        and str(item.get("Subject Code", code)) == code
        for item in existing_rows
    ):
        return
    file_has_content = os.path.isfile(path) and os.path.getsize(path) > 0
    encoding = "utf-8" if file_has_content else "utf-8-sig"
    with open(path, "a", newline="", encoding=encoding) as file:
        fieldnames = ["Student ID", "Name", "Subject", "Subject Code", "Date", "Time", "Status"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not file_has_content:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fieldnames})


def record_attendance_once(student_id, subject_id):
    """Create at most one record for a student, subject and calendar date."""
    student = attendance_system.students.get(student_id)
    subject = get_subject(subject_id, DB_PATH, active_only=True)
    if not student or not subject:
        return False
    current_date = today_string()
    current_time = datetime.now().strftime("%H:%M:%S")
    inserted = insert_attendance_once(
        student_id,
        student["name"],
        current_date,
        current_time,
        "Present",
        DB_PATH,
        subject_id=int(subject_id),
    )
    if inserted:
        try:
            append_attendance_csv({
                "Student ID": student_id,
                "Name": student["name"],
                "Subject": subject["name"],
                "Subject Code": subject["code"],
                "Date": current_date,
                "Time": current_time,
                "Status": "Present",
            })
        except OSError:
            app.logger.exception("Attendance was saved to SQLite but its CSV mirror failed.")
    return inserted


def parse_report_range():
    today = date.today()
    period = request.args.get("period", "daily").lower()
    if period not in {"daily", "weekly", "monthly", "custom"}:
        period = "daily"
    if period == "daily":
        start, end = today, today
    elif period == "weekly":
        start, end = today - timedelta(days=today.weekday()), today
    elif period == "monthly":
        start, end = today.replace(day=1), today
    else:
        try:
            start = date.fromisoformat(request.args.get("start", ""))
            end = date.fromisoformat(request.args.get("end", ""))
            if end < start:
                raise ValueError("End date must be on or after start date.")
            if end > today:
                end = today
            if start > today:
                raise ValueError("Start date cannot be in the future.")
        except ValueError as error:
            flash(f"Invalid custom date range ({error}). Showing today's report instead.", "error")
            period = "daily"
            start = end = today
    return period, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def build_student_summaries(start_date=None, end_date=None, subject_id=None):
    """Summarize presence against each recorded subject session in the date range."""
    active_students = attendance_system.students
    metadata = {row["student_id"]: row for row in get_student_metadata(DB_PATH, active_only=True)}
    session_rows = get_subject_session_rows(start_date, end_date, DB_PATH, subject_id=subject_id)
    attendance_rows = read_all_attendance(start_date, end_date, subject_id=subject_id)
    present_by_student = {}
    for row in attendance_rows:
        present_by_student.setdefault(row["Student ID"], set()).add((int(row["Subject ID"]), row["Date"]))

    summaries = []
    for student_id, student in active_students.items():
        db_student = metadata.get(student_id, {})
        enrolled_on = db_student.get("enrolled_on") or start_date or today_string()
        eligible_sessions = [
            (int(session["subject_id"]), session["session_date"])
            for session in session_rows
            if session["session_date"] >= enrolled_on
        ]
        present_pairs = present_by_student.get(student_id, set())
        present = sum(1 for pair in eligible_sessions if pair in present_pairs)
        total_sessions = len(eligible_sessions)
        absent = max(total_sessions - present, 0)
        rate = round((present / total_sessions) * 100, 1) if total_sessions else None
        student_history = [row for row in attendance_rows if row["Student ID"] == student_id]
        summaries.append({
            "student_id": student_id,
            "name": student["name"],
            "email": db_student.get("email", ""),
            "enrolled_on": enrolled_on,
            "sessions": total_sessions,
            "present": present,
            "absent": absent,
            "attendance_rate": rate,
            "last_seen": (student_history[0]["Date"] + " " + student_history[0]["Time"]) if student_history else "—",
        })
    summaries.sort(key=lambda item: (item["attendance_rate"] is None, item["attendance_rate"] if item["attendance_rate"] is not None else 101, item["name"].casefold()))
    return summaries


def get_low_attendance_students(threshold=None, subject_id=None):
    if threshold is None:
        try:
            threshold = float(get_setting("low_attendance_threshold", "75", DB_PATH))
        except ValueError:
            threshold = 75.0
    session_rows = get_subject_session_rows(None, today_string(), DB_PATH, subject_id=subject_id)
    first_date = min((row["session_date"] for row in session_rows), default=today_string())
    summaries = build_student_summaries(first_date, today_string(), subject_id=subject_id)
    return [student for student in summaries if student["attendance_rate"] is not None and student["sessions"] > 0 and student["attendance_rate"] < threshold]


def email_notifications_configured():
    return all(os.environ.get(key) for key in (
        "ATTENDAI_SMTP_HOST", "ATTENDAI_SMTP_FROM", "ATTENDAI_SMTP_PASSWORD"
    ))


def student_rows():
    summaries = build_student_summaries(None, today_string())
    by_id = {item["student_id"]: item for item in summaries}
    rows = read_all_attendance()
    result = []
    for student_id, record in sorted(attendance_system.students.items(), key=lambda item: item[1]["name"].casefold()):
        history = [row for row in rows if row["Student ID"] == student_id]
        summary = by_id.get(student_id, {})
        last_seen = "—"
        if history:
            most_recent = sorted(history, key=lambda row: (row["Date"], row["Time"]))[-1]
            last_seen = f'{most_recent["Date"]} {most_recent["Time"]}'
        result.append({
            "student_id": student_id,
            "name": record["name"],
            "email": summary.get("email", ""),
            "attendance_count": len(history),
            "attendance_rate": summary.get("attendance_rate"),
            "last_seen": last_seen,
        })
    return result


@app.route("/subjects", methods=["GET", "POST"])
def subjects():
    if request.method == "POST":
        name = str(request.form.get("name", "")).strip()
        code = str(request.form.get("code", "")).strip().upper()
        if not name or len(name) > 80 or any(ch in name for ch in "\r\n"):
            flash("Enter a subject name of up to 80 characters.", "error")
            return redirect(url_for("subjects"))
        if not re.fullmatch(r"[A-Z0-9_-]{2,15}", code):
            flash("Use 2–15 letters, numbers, hyphens or underscores for the subject code.", "error")
            return redirect(url_for("subjects"))
        try:
            create_subject(name, code, DB_PATH)
            flash(f"Subject {name} ({code}) created successfully.", "success")
        except sqlite3.IntegrityError:
            flash("That subject name or code already exists. Choose a unique one.", "error")
        return redirect(url_for("subjects"))
    return render_template("subjects.html", subjects=get_subjects(DB_PATH, active_only=False))


@app.route("/")
def dashboard():
    total = len(attendance_system.students)
    rows = get_today_rows()
    present_ids = {row.get("Student ID") for row in rows}
    present_ids.discard(None)
    present = len(present_ids)
    today_subject_sessions = get_subject_session_rows(today_string(), today_string(), DB_PATH)
    has_session = bool(today_subject_sessions)
    absent = max(total - present, 0) if has_session else 0
    rate = round((present / total) * 100) if total and has_session else 0
    recent_rows = rows[:8]
    stats = {
        "total_students": total,
        "present_today": present,
        "absent_today": absent,
        "attendance_rate": rate,
        "session_active": has_session,
        "total_sessions": len(get_subject_session_rows(None, today_string(), DB_PATH)),
    }
    threshold = float(get_setting("low_attendance_threshold", "75", DB_PATH))
    low_students = get_low_attendance_students(threshold)[:8]
    return render_template(
        "dashboard.html", stats=stats, recent_rows=recent_rows,
        current_date=datetime.now().strftime("%d %b %Y"),
        low_students=low_students, low_threshold=threshold,
        email_notifications_configured=email_notifications_configured(),
    )


@app.route("/students")
def students():
    return render_template("students.html", students=student_rows(), low_threshold=float(get_setting("low_attendance_threshold", "75", DB_PATH)))


@app.route("/students/add")
def add_student():
    return render_template("add_student.html")


@app.route("/students/<student_id>/email", methods=["POST"])
def update_student_email_route(student_id):
    if student_id not in attendance_system.students:
        flash("Student profile was not found.", "error")
        return redirect(url_for("students"))
    email = str(request.form.get("email", "")).strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        flash("Enter a valid email address or leave it blank.", "error")
        return redirect(url_for("students"))
    update_student_email(student_id, email, DB_PATH)
    flash(f"Email details saved for {student_id}.", "success")
    return redirect(url_for("students"))


@app.route("/students/<student_id>/delete", methods=["POST"])
def delete_student(student_id):
    if student_id not in attendance_system.students:
        flash("Student face profile was not found.", "error")
        return redirect(url_for("students"))
    path = os.path.join(attendance_system.students_dir, f"{student_id}.npz")
    try:
        if os.path.isfile(path):
            os.remove(path)
        attendance_system.students.pop(student_id, None)
        attendance_system.face_system.known_faces.pop(student_id, None)
        deactivate_student(student_id, DB_PATH)
        # Drop the challenge state so a deleted face cannot reuse an old verification.
        for client_id in list(liveness_sessions.keys()):
            liveness_sessions[client_id].pop(student_id, None)
            if not liveness_sessions[client_id]:
                liveness_sessions.pop(client_id, None)
        flash(f"{student_id} was removed from active recognition. Historical attendance was preserved.", "success")
    except OSError as error:
        app.logger.exception("Could not delete student profile")
        flash(f"Could not delete the profile: {error}", "error")
    return redirect(url_for("students"))


@app.route("/api/register_student", methods=["POST"])
def api_register_student():
    data = request.get_json(silent=True) or {}
    student_id = str(data.get("student_id", "")).strip()
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip()
    image_data = data.get("image")

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", student_id):
        return jsonify({"success": False, "message": "Use 1–30 letters, numbers, hyphens or underscores for the Student ID."}), 400
    if not name or len(name) > 80 or any(ch in name for ch in ",\r\n"):
        return jsonify({"success": False, "message": "Enter a name of up to 80 characters. Commas and line breaks are not allowed."}), 400
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify({"success": False, "message": "Enter a valid email address or leave it blank."}), 400
    if student_id in attendance_system.students:
        return jsonify({"success": False, "message": "That Student ID is already registered. Use a different ID."}), 409

    try:
        frame = decode_image(image_data)
        if frame is None:
            return jsonify({"success": False, "message": "Could not read the captured image."}), 400
        faces = attendance_system.face_system.detect_faces(frame)
        if len(faces) == 0:
            return jsonify({"success": False, "message": "No face detected. Improve lighting and try again."}), 400
        if len(faces) > 1:
            return jsonify({"success": False, "message": "More than one face detected. Make sure only one person is in frame."}), 400
        feature = attendance_system.face_system.extract_face_feature(frame, faces[0])
        os.makedirs(attendance_system.students_dir, exist_ok=True)
        path = os.path.join(attendance_system.students_dir, f"{student_id}.npz")
        np.savez(path, student_id=student_id, name=name, feature=feature)
        attendance_system.students[student_id] = {"name": name, "feature": feature}
        attendance_system.face_system.add_known_face(student_id, feature)
        sync_student_profile(student_id, name, today_string(), email=email, db_path=DB_PATH)
        return jsonify({"success": True, "message": f"{name} was registered successfully.", "student_id": student_id, "name": name}), 201
    except (ValueError, TypeError, base64.binascii.Error) as error:
        app.logger.warning("Invalid enrollment image: %s", error)
        return jsonify({"success": False, "message": "The captured image could not be processed. Please try again."}), 400
    except Exception:
        app.logger.exception("Student enrollment failed")
        return jsonify({"success": False, "message": "Enrollment failed. Check the server terminal for details."}), 500


@app.route("/attendance")
def attendance():
    active_subjects = get_subjects(DB_PATH, active_only=True)
    return render_template("attendance.html", subjects=active_subjects)


@app.route("/api/liveness/reset", methods=["POST"])
def reset_liveness():
    data = request.get_json(silent=True) or {}
    client_id = str(data.get("client_id", "")).strip()
    if not client_id or len(client_id) > 100:
        return jsonify({"success": False, "message": "Invalid camera session."}), 400
    liveness_sessions.pop(client_id, None)
    return jsonify({"success": True})


@app.route("/api/recognize", methods=["POST"])
def recognize():
    data = request.get_json(silent=True) or {}
    client_id = str(data.get("client_id", "")).strip()
    subject_id = data.get("subject_id")
    subject = get_subject(subject_id, DB_PATH, active_only=True)
    if not client_id or len(client_id) > 100:
        return jsonify({"success": False, "message": "Restart the camera to begin a liveness session."}), 400
    if not subject:
        return jsonify({"success": False, "message": "Select an active subject before starting attendance."}), 400
    try:
        frame = decode_image(data.get("image"))
        if frame is None:
            return jsonify({"success": False, "message": "No valid image was received."}), 400
        # Each subject/date is a distinct lecture session in the attendance denominator.
        record_subject_session(int(subject["subject_id"]), today_string(), DB_PATH)
        faces = attendance_system.face_system.detect_faces(frame)
        results = []
        marked_ids = {row.get("Student ID") for row in get_today_rows(int(subject["subject_id"]))}

        for face in faces:
            x, y, width, height = [int(round(value)) for value in face[:4]]
            box = [x, y, width, height]
            feature = attendance_system.face_system.extract_face_feature(frame, face)
            student_id, score = attendance_system.face_system.recognize_face(feature)
            if student_id is None or student_id not in attendance_system.students:
                results.append({
                    "student_id": None, "name": "Unknown", "status": "Unknown",
                    "liveness": "unknown", "anti_spoof": "not_checked",
                    "overlay_label": "UNKNOWN FACE", "score": round(float(score), 3), "bbox": box,
                })
                continue

            student = attendance_system.students[student_id]
            live = advance_liveness(client_id, student_id, face)
            if not live["verified"]:
                results.append({
                    "student_id": student_id,
                    "name": student["name"],
                    "status": live["message"],
                    "liveness": "pending",
                    "anti_spoof": "disabled",
                    "overlay_label": "VERIFYING HEAD MOVEMENT",
                    "challenge": live["message"],
                    "newly_marked": False,
                    "score": round(float(score), 3),
                    "bbox": box,
                })
                continue

            newly_marked = record_attendance_once(student_id, int(subject["subject_id"])) if student_id not in marked_ids else False
            marked_ids.add(student_id)
            status_label = "Present" if newly_marked else "Already Marked"
            results.append({
                "student_id": student_id,
                "name": student["name"],
                "status": status_label,
                "subject": subject["name"],
                "subject_code": subject["code"],
                "liveness": "verified",
                "anti_spoof": "disabled",
                "overlay_label": f"{student['name']} · {'PRESENT' if newly_marked else 'ALREADY MARKED'}",
                "newly_marked": newly_marked,
                "score": round(float(score), 3),
                "bbox": box,
            })
        return jsonify({"success": True, "face_count": len(faces), "results": results})
    except (ValueError, TypeError, base64.binascii.Error) as error:
        app.logger.warning("Invalid recognition frame: %s", error)
        return jsonify({"success": False, "message": "The camera frame could not be processed."}), 400
    except Exception:
        app.logger.exception("Recognition request failed")
        return jsonify({"success": False, "message": "Recognition failed. Check the server terminal for details."}), 500


@app.route("/reports")
def reports():
    period, start_date, end_date = parse_report_range()
    raw_subject_id = request.args.get("subject_id", "all")
    selected_subject = None
    if raw_subject_id not in ("", "all"):
        selected_subject = get_subject(raw_subject_id, DB_PATH, active_only=False)
        if not selected_subject:
            flash("The selected subject was not found. Showing all subjects.", "error")
            raw_subject_id = "all"
    selected_subject_id = int(selected_subject["subject_id"]) if selected_subject else None
    all_rows = read_all_attendance(start_date, end_date, selected_subject_id)
    session_rows = get_subject_session_rows(start_date, end_date, DB_PATH, subject_id=selected_subject_id)
    summaries = build_student_summaries(start_date, end_date, subject_id=selected_subject_id)
    threshold = float(get_setting("low_attendance_threshold", "75", DB_PATH))
    low_students = [item for item in summaries if item["attendance_rate"] is not None and item["sessions"] > 0 and item["attendance_rate"] < threshold]
    return render_template(
        "reports.html", record_count=len(all_rows), student_count=len(attendance_system.students),
        rows=all_rows, summaries=summaries, session_count=len(session_rows), period=period,
        start_date=start_date, end_date=end_date, low_students=low_students,
        low_threshold=threshold, email_notifications_configured=email_notifications_configured(),
        subjects=get_subjects(DB_PATH, active_only=False), selected_subject_id=(str(selected_subject_id) if selected_subject_id is not None else "all"),
        selected_subject=selected_subject,
    )


def report_export_rows():
    _, start_date, end_date = parse_report_range()
    raw_subject_id = request.args.get("subject_id", "all")
    selected_subject = get_subject(raw_subject_id, DB_PATH, active_only=False) if raw_subject_id not in ("", "all") else None
    subject_id = int(selected_subject["subject_id"]) if selected_subject else None
    return start_date, end_date, read_all_attendance(start_date, end_date, subject_id), build_student_summaries(start_date, end_date, subject_id), selected_subject


@app.route("/reports/export")
def export_report():
    start_date, end_date, rows, summaries, selected_subject = report_export_rows()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["AttendAI Attendance Report", start_date, "to", end_date, "Subject", selected_subject["name"] if selected_subject else "All subjects"])
    writer.writerow([])
    writer.writerow(["Student ID", "Name", "Present Sessions", "Eligible Sessions", "Absent Sessions", "Attendance %", "Email"])
    for item in summaries:
        writer.writerow([item["student_id"], item["name"], item["present"], item["sessions"], item["absent"], "" if item["attendance_rate"] is None else item["attendance_rate"], item["email"]])
    writer.writerow([])
    writer.writerow(["ATTENDANCE EVENTS"])
    writer.writerow(["Student ID", "Name", "Subject", "Subject Code", "Date", "Time", "Status"])
    for row in rows:
        writer.writerow([row.get("Student ID", ""), row.get("Name", ""), row.get("Subject", ""), row.get("Subject Code", ""), row.get("Date", ""), row.get("Time", ""), row.get("Status", "")])
    payload = BytesIO(output.getvalue().encode("utf-8-sig"))
    payload.seek(0)
    subject_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", selected_subject["code"]) if selected_subject else "all_subjects"
    return send_file(payload, mimetype="text/csv", as_attachment=True, download_name=f"AttendAI_{subject_slug}_{start_date}_to_{end_date}.csv")


@app.route("/reports/export.pdf")
def export_pdf_report():
    start_date, end_date, rows, summaries, selected_subject = report_export_rows()
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, LongTable
    except ImportError:
        flash("PDF export needs ReportLab. Run: python -m pip install reportlab", "error")
        return redirect(url_for("reports", period=request.args.get("period", "daily"), start=start_date, end=end_date, subject_id=request.args.get("subject_id", "all")))

    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm, topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    subject_label = selected_subject["name"] if selected_subject else "All subjects"
    session_count_for_range = len(get_subject_session_rows(start_date, end_date, DB_PATH, subject_id=selected_subject["subject_id"] if selected_subject else None))
    elements = [
        Paragraph("AttendAI — Attendance Report", styles["Title"]),
        Paragraph(f"Subject: {html_escape(subject_label)}", styles["Heading2"]),
        Paragraph(f"Reporting period: {html_escape(start_date)} to {html_escape(end_date)}", styles["Normal"]),
        Paragraph(f"Active students: {len(attendance_system.students)} · Attendance events: {len(rows)} · Subject sessions: {session_count_for_range}", styles["Normal"]),
        Spacer(1, 8*mm),
        Paragraph("Student summary", styles["Heading2"]),
    ]
    summary_data = [["Student ID", "Student", "Present", "Eligible sessions", "Absent", "Attendance %"]]
    for item in summaries:
        summary_data.append([item["student_id"], item["name"], str(item["present"]), str(item["sessions"]), str(item["absent"]), "—" if item["attendance_rate"] is None else f'{item["attendance_rate"]}%'])
    if len(summary_data) == 1:
        summary_data.append(["—", "No enrolled students", "0", "0", "0", "—"])
    summary_table = LongTable(summary_data, repeatRows=1, colWidths=[28*mm, 52*mm, 22*mm, 32*mm, 22*mm, 28*mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172554")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dbe2ea")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fb")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.extend([summary_table, Spacer(1, 8*mm), Paragraph("Attendance events", styles["Heading2"])])
    event_data = [["Student ID", "Name", "Subject", "Date", "Time", "Status"]]
    for item in rows:
        event_data.append([item.get("Student ID", ""), item.get("Name", ""), item.get("Subject Code", ""), item.get("Date", ""), item.get("Time", ""), item.get("Status", "")])
    if len(event_data) == 1:
        event_data.append(["—", "No attendance events in this period", "—", "—", "—", "—"])
    event_table = LongTable(event_data, repeatRows=1, colWidths=[28*mm, 50*mm, 28*mm, 27*mm, 24*mm, 28*mm])
    event_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172554")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dbe2ea")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fb")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(event_table)
    document.build(elements)
    buffer.seek(0)
    subject_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", selected_subject["code"]) if selected_subject else "all_subjects"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"AttendAI_{subject_slug}_{start_date}_to_{end_date}.pdf")


@app.route("/notifications/send-low-attendance", methods=["POST"])
def send_low_attendance_notifications():
    if not email_notifications_configured():
        flash("Email is not configured. Set ATTENDAI_SMTP_HOST, ATTENDAI_SMTP_FROM and ATTENDAI_SMTP_PASSWORD before sending email alerts. In-app low-attendance alerts are still available.", "error")
        return redirect(request.referrer or url_for("reports"))
    raw_subject_id = request.args.get("subject_id", "all")
    selected_subject = get_subject(raw_subject_id, DB_PATH, active_only=False) if raw_subject_id not in ("", "all") else None
    selected_subject_id = int(selected_subject["subject_id"]) if selected_subject else None
    low_students = get_low_attendance_students(subject_id=selected_subject_id)
    recipients = [item for item in low_students if item.get("email")]
    if not recipients:
        flash("No low-attendance students with an email address were found.", "warning")
        return redirect(request.referrer or url_for("reports"))

    threshold = float(get_setting("low_attendance_threshold", "75", DB_PATH))
    host = os.environ["ATTENDAI_SMTP_HOST"]
    port = int(os.environ.get("ATTENDAI_SMTP_PORT", "587"))
    sender = os.environ["ATTENDAI_SMTP_FROM"]
    username = os.environ.get("ATTENDAI_SMTP_USERNAME", "")
    password = os.environ["ATTENDAI_SMTP_PASSWORD"]
    sent = 0
    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            if username:
                server.login(username, password)
            for student in recipients:
                message = EmailMessage()
                message["Subject"] = "AttendAI: Attendance below required threshold"
                message["From"] = sender
                message["To"] = student["email"]
                rate = student["attendance_rate"]
                subject_line = f"Subject: {selected_subject['name']}. " if selected_subject else "Across all subjects. "
                message.set_content(
                    f"Hello {student['name']},\n\n"
                    f"Your recorded attendance is {rate}% across {student['sessions']} eligible sessions. "
                    + subject_line
                    + f"The current threshold is {threshold}%. Please contact your faculty if you believe this record is incorrect.\n\n"
                    + "This is an automated message from AttendAI."
                )
                server.send_message(message)
                sent += 1
        flash(f"Low-attendance email notification(s) sent: {sent}.", "success")
    except Exception as error:
        app.logger.exception("Failed to send low-attendance notification email")
        flash(f"Email sending failed. Check SMTP configuration. Details: {error}", "error")
    return redirect(request.referrer or url_for("reports"))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            threshold = float(request.form.get("low_attendance_threshold", "75"))
            if not 1 <= threshold <= 100:
                raise ValueError
            set_setting("low_attendance_threshold", str(threshold), DB_PATH)
            flash(f"Low-attendance threshold updated to {threshold:g}%.", "success")
        except ValueError:
            flash("Enter a threshold between 1 and 100.", "error")
        return redirect(url_for("settings"))
    return render_template(
        "settings.html",
        student_count=len(attendance_system.students),
        low_attendance_threshold=get_setting("low_attendance_threshold", "75", DB_PATH),
        email_notifications_configured=email_notifications_configured(),
        total_sessions=len(get_subject_session_rows(None, today_string(), DB_PATH)),
    )


# ---------------- Authentication and role-based access ----------------
# User credentials live in the existing SQLite database. Passwords are stored as
# Werkzeug password hashes, never as plaintext. The first page visit creates the
# first administrator; there is no public registration after setup is complete.

def auth_connection():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_auth_schema():
    connection = auth_connection()
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS auth_users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'faculty')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.commit()
    finally:
        connection.close()


def auth_user_count():
    connection = auth_connection()
    try:
        return int(connection.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0])
    finally:
        connection.close()


def get_auth_user(user_id):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    connection = auth_connection()
    try:
        row = connection.execute(
            "SELECT user_id, username, display_name, role, active, created_at "
            "FROM auth_users WHERE user_id = ? AND active = 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def get_auth_user_by_username(username):
    connection = auth_connection()
    try:
        row = connection.execute(
            "SELECT * FROM auth_users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def list_auth_users():
    connection = auth_connection()
    try:
        rows = connection.execute(
            "SELECT user_id, username, display_name, role, active, created_at "
            "FROM auth_users ORDER BY role, username COLLATE NOCASE"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def csrf_is_valid():
    expected = session.get("_csrf_token")
    supplied = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token")
    return bool(expected and supplied and hmac.compare_digest(str(expected), str(supplied)))


def safe_local_redirect(candidate):
    if isinstance(candidate, str) and candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return url_for("dashboard")


@app.before_request
def enforce_authentication_and_permissions():
    g.current_user = get_auth_user(session.get("user_id"))

    if request.endpoint == "static":
        return None

    # Protect all POST requests from cross-site form submissions, including login/setup.
    if request.method == "POST" and not csrf_is_valid():
        abort(400, description="Your form session expired. Refresh the page and try again.")

    if request.endpoint == "setup":
        if auth_user_count() > 0:
            return redirect(url_for("dashboard") if g.current_user else url_for("login"))
        return None

    if request.endpoint == "login":
        if auth_user_count() == 0:
            return redirect(url_for("setup"))
        if g.current_user:
            return redirect(url_for("dashboard"))
        return None

    if not g.current_user:
        session["next_url"] = request.full_path if request.query_string else request.path
        return redirect(url_for("login"))

    admin_only = {
        "accounts", "create_account", "toggle_account", "add_student",
        "api_register_student", "delete_student", "update_student_email_route",
        "settings",
    }
    if request.endpoint in admin_only and g.current_user["role"] != "admin":
        flash("Administrator permission is required for that action.", "error")
        return redirect(url_for("dashboard"))

    if request.endpoint == "subjects" and request.method == "POST" and g.current_user["role"] != "admin":
        flash("Only an administrator can create subjects.", "error")
        return redirect(url_for("subjects"))

    return None


@app.context_processor
def inject_auth_template_values():
    return {
        "current_user": getattr(g, "current_user", None),
        "csrf_token": csrf_token,
    }


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if request.method == "POST":
        username = str(request.form.get("username", "")).strip()
        display_name = str(request.form.get("display_name", "")).strip()
        password = str(request.form.get("password", ""))
        confirm_password = str(request.form.get("confirm_password", ""))

        if auth_user_count() > 0:
            flash("Initial setup is already complete. Please sign in.", "error")
            return redirect(url_for("login"))
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            flash("Username must be 3–32 characters using letters, numbers, dots, underscores or hyphens.", "error")
        elif not display_name or len(display_name) > 80 or any(ch in display_name for ch in "\r\n"):
            flash("Enter a display name of up to 80 characters.", "error")
        elif len(password) < 10:
            flash("Use a password with at least 10 characters.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            connection = auth_connection()
            try:
                cursor = connection.execute(
                    "INSERT INTO auth_users(username, display_name, password_hash, role, active) VALUES (?, ?, ?, 'admin', 1)",
                    (username, display_name, generate_password_hash(password)),
                )
                connection.commit()
                user_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                flash("That username is already in use. Choose another.", "error")
                return render_template("setup.html", username=username, display_name=display_name)
            finally:
                connection.close()

            session.clear()
            session["user_id"] = int(user_id)
            session.permanent = True
            csrf_token()
            flash("Administrator account created. Welcome to AttendAI.", "success")
            return redirect(url_for("dashboard"))

        return render_template("setup.html", username=username, display_name=display_name)

    return render_template("setup.html", username="", display_name="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = str(request.form.get("username", "")).strip()
        password = str(request.form.get("password", ""))
        user = get_auth_user_by_username(username)
        if user and user.get("active") and check_password_hash(user["password_hash"], password):
            next_url = session.pop("next_url", None)
            session.clear()
            session["user_id"] = int(user["user_id"])
            session.permanent = True
            csrf_token()
            flash(f"Welcome back, {user['display_name']}.", "success")
            return redirect(safe_local_redirect(next_url))
        flash("Invalid username or password, or the account is disabled.", "error")
    return render_template("login.html", username=str(request.form.get("username", "")) if request.method == "POST" else "")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/accounts")
def accounts():
    return render_template("accounts.html", accounts=list_auth_users())


@app.route("/accounts/create", methods=["POST"])
def create_account():
    username = str(request.form.get("username", "")).strip()
    display_name = str(request.form.get("display_name", "")).strip()
    password = str(request.form.get("password", ""))
    confirm_password = str(request.form.get("confirm_password", ""))
    role = str(request.form.get("role", "faculty")).strip().lower()

    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
        flash("Username must be 3–32 characters using letters, numbers, dots, underscores or hyphens.", "error")
    elif not display_name or len(display_name) > 80 or any(ch in display_name for ch in "\r\n"):
        flash("Enter a valid display name.", "error")
    elif role not in {"faculty", "admin"}:
        flash("Select a valid account role.", "error")
    elif len(password) < 10:
        flash("Use a password with at least 10 characters.", "error")
    elif password != confirm_password:
        flash("Passwords do not match.", "error")
    else:
        connection = auth_connection()
        try:
            connection.execute(
                "INSERT INTO auth_users(username, display_name, password_hash, role, active) VALUES (?, ?, ?, ?, 1)",
                (username, display_name, generate_password_hash(password), role),
            )
            connection.commit()
            flash(f"{role.title()} account created for {display_name}.", "success")
        except sqlite3.IntegrityError:
            flash("That username already exists. Choose another.", "error")
        finally:
            connection.close()
    return redirect(url_for("accounts"))


@app.route("/accounts/<int:user_id>/toggle", methods=["POST"])
def toggle_account(user_id):
    if g.current_user and int(g.current_user["user_id"]) == user_id:
        flash("You cannot disable the account you are currently using.", "error")
        return redirect(url_for("accounts"))

    connection = auth_connection()
    try:
        target = connection.execute(
            "SELECT user_id, username, display_name, role, active FROM auth_users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not target:
            flash("Account not found.", "error")
        elif target["role"] == "admin":
            flash("Administrator accounts cannot be disabled from this screen.", "error")
        else:
            new_active = 0 if target["active"] else 1
            connection.execute("UPDATE auth_users SET active = ? WHERE user_id = ?", (new_active, user_id))
            connection.commit()
            status = "enabled" if new_active else "disabled"
            flash(f"Account {target['username']} has been {status}.", "success")
    finally:
        connection.close()
    return redirect(url_for("accounts"))



# Initialize and migrate the database before the Flask server serves its first request.
sync_legacy_data()
init_auth_schema()


if __name__ == "__main__":
    # Disable the reloader so the face engine is not initialized twice.
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
