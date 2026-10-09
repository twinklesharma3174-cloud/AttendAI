import cv2
import os
import numpy as np

from src.face_recognition_system import FaceRecognitionSystem


class StudentRegistration:

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

        os.makedirs(self.students_dir, exist_ok=True)

    def register_student(self, student_id, name):

        camera = cv2.VideoCapture(0)

        if not camera.isOpened():
            print("Error: Could not open webcam.")
            return False

        print("\nCamera started.")
        print("Look directly at the camera.")
        print("Press SPACE to capture your face.")
        print("Press ESC to cancel.\n")

        captured_feature = None

        while True:

            success, frame = camera.read()

            if not success:
                print("Error: Could not read webcam frame.")
                break

            faces = self.face_system.detect_faces(frame)

            if len(faces) > 0:

                for face in faces:

                    x, y, w, h = face[:4].astype(int)

                    cv2.rectangle(
                        frame,
                        (x, y),
                        (x + w, y + h),
                        (0, 255, 0),
                        2
                    )

                    cv2.putText(
                        frame,
                        "Face detected",
                        (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2
                    )

            cv2.putText(
                frame,
                "SPACE = Capture | ESC = Cancel",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2
            )

            cv2.imshow(
                "AttendAI - Student Registration",
                frame
            )

            key = cv2.waitKey(1) & 0xFF

            if key == 32:

                if len(faces) == 0:
                    print("No face detected. Try again.")
                    continue

                if len(faces) > 1:
                    print("Multiple faces detected.")
                    print("Only one person should be visible.")
                    continue

                captured_feature = (
                    self.face_system.extract_face_feature(
                        frame,
                        faces[0]
                    )
                )

                break

            elif key == 27:

                print("Registration cancelled.")

                camera.release()
                cv2.destroyAllWindows()

                return False

        camera.release()
        cv2.destroyAllWindows()

        if captured_feature is None:
            return False

        student_file = os.path.join(
            self.students_dir,
            f"{student_id}.npz"
        )

        np.savez(
            student_file,
            student_id=student_id,
            name=name,
            feature=captured_feature
        )

        print("\nStudent registered successfully!")
        print(f"Student ID: {student_id}")
        print(f"Name: {name}")
        print(f"Saved to: {student_file}")

        return True