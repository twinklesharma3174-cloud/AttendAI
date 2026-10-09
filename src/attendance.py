import cv2
import os
import numpy as np
from datetime import datetime

from src.face_recognition_system import FaceRecognitionSystem


class AttendanceSystem:

    def __init__(self):

        self.face_system = FaceRecognitionSystem()

        self.base_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )

        self.students_dir = os.path.join(
            self.base_dir,
            "data",
            "students"
        )

        self.attendance_dir = os.path.join(
            self.base_dir,
            "attendance"
        )

        os.makedirs(self.attendance_dir, exist_ok=True)

        self.students = {}

        self.load_students()

    def load_students(self):

        if not os.path.exists(self.students_dir):
            return

        for filename in os.listdir(self.students_dir):

            if not filename.endswith(".npz"):
                continue

            file_path = os.path.join(
                self.students_dir,
                filename
            )

            data = np.load(
                file_path,
                allow_pickle=True
            )

            student_id = str(data["student_id"])
            name = str(data["name"])
            feature = data["feature"]

            self.students[student_id] = {
                "name": name,
                "feature": feature
            }

            self.face_system.add_known_face(
                student_id,
                feature
            )

        print(
            f"Loaded {len(self.students)} registered student(s)."
        )

    def mark_attendance(self, student_id):

        today = datetime.now().strftime("%Y-%m-%d")

        attendance_file = os.path.join(
            self.attendance_dir,
            f"attendance_{today}.csv"
        )

        file_exists = os.path.exists(
            attendance_file
        )

        already_present = False

        if file_exists:

            with open(
                attendance_file,
                "r",
                encoding="utf-8"
            ) as file:

                for line in file:

                    if line.startswith(student_id + ","):
                        already_present = True
                        break

        if already_present:
            return False

        current_time = datetime.now().strftime(
            "%H:%M:%S"
        )

        with open(
            attendance_file,
            "a",
            encoding="utf-8"
        ) as file:

            if not file_exists:

                file.write(
                    "Student ID,Name,Date,Time,Status\n"
                )

            name = self.students[
                student_id
            ]["name"]

            file.write(
                f"{student_id},{name},{today},"
                f"{current_time},Present\n"
            )

        return True

    def start_attendance(self):

        camera = cv2.VideoCapture(0)

        if not camera.isOpened():

            print(
                "Error: Could not open webcam."
            )

            return

        print("\n" + "=" * 50)
        print("       AttendAI Attendance System")
        print("=" * 50)
        print("Look at the camera.")
        print("Press ESC to stop attendance.")
        print("=" * 50 + "\n")

        while True:

            success, frame = camera.read()

            if not success:

                print(
                    "Error: Could not read webcam."
                )

                break

            faces = self.face_system.detect_faces(
                frame
            )

            for face in faces:

                x, y, w, h = face[:4].astype(int)

                feature = (
                    self.face_system
                    .extract_face_feature(
                        frame,
                        face
                    )
                )

                student_id, score = (
                    self.face_system
                    .recognize_face(feature)
                )

                if student_id is not None:

                    name = self.students[
                        student_id
                    ]["name"]

                    attendance_marked = (
                        self.mark_attendance(
                            student_id
                        )
                    )

                    label = (
                        f"{name} - Present"
                    )

                    if not attendance_marked:

                        label = (
                            f"{name} - Already Marked"
                        )

                    cv2.rectangle(
                        frame,
                        (x, y),
                        (x + w, y + h),
                        (0, 255, 0),
                        2
                    )

                    cv2.putText(
                        frame,
                        label,
                        (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (0, 255, 0),
                        2
                    )

                else:

                    cv2.rectangle(
                        frame,
                        (x, y),
                        (x + w, y + h),
                        (0, 0, 255),
                        2
                    )

                    cv2.putText(
                        frame,
                        "Unknown",
                        (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (0, 0, 255),
                        2
                    )

            cv2.putText(
                frame,
                "ESC = Exit",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2
            )

            cv2.imshow(
                "AttendAI - Attendance",
                frame
            )

            key = cv2.waitKey(1) & 0xFF

            if key == 27:
                break

        camera.release()
        cv2.destroyAllWindows()