import cv2
import numpy as np
import os


class FaceRecognitionSystem:

    def __init__(self):
        base_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )

        detector_model = os.path.join(
            base_dir,
            "models",
            "face_detection_yunet_2023mar.onnx"
        )

        recognizer_model = os.path.join(
            base_dir,
            "models",
            "face_recognition_sface_2021dec.onnx"
        )

        # Create YuNet face detector
        self.detector = cv2.FaceDetectorYN.create(
            detector_model,
            "",
            (320, 320),
            0.9,
            0.3,
            5000
        )

        # Create SFace recognizer
        self.recognizer = cv2.FaceRecognizerSF.create(
            recognizer_model,
            ""
        )

        self.known_faces = {}

    def detect_faces(self, frame):
        """Detect faces in an image/frame."""

        height, width = frame.shape[:2]

        self.detector.setInputSize((width, height))

        _, faces = self.detector.detect(frame)

        if faces is None:
            return []

        return faces

    def extract_face_feature(self, frame, face):
        """Extract the SFace feature from a detected face."""

        aligned_face = self.recognizer.alignCrop(
            frame,
            face
        )

        feature = self.recognizer.feature(
            aligned_face
        )

        return feature

    def compare_faces(self, feature1, feature2):
        """Calculate cosine similarity between two face features."""

        score = self.recognizer.match(
            feature1,
            feature2,
            cv2.FaceRecognizerSF_FR_COSINE
        )

        return score

    def add_known_face(self, student_id, feature):
        """Store a student's face feature."""

        self.known_faces[student_id] = feature

    def recognize_face(self, feature, threshold=0.363):
        """Find the best matching registered student."""

        best_match = None
        best_score = -1

        for student_id, known_feature in self.known_faces.items():

            score = self.compare_faces(
                feature,
                known_feature
            )

            if score > best_score:
                best_score = score
                best_match = student_id

        if best_score >= threshold:
            return best_match, best_score

        return None, best_score