import os

import cv2
import numpy as np
import onnxruntime as ort


class FaceAntiSpoofing:
    """MiniFASNet-V2 ONNX face presentation-attack detector.

    The model produces three softmax probabilities. In the upstream
    Silent-Face-Anti-Spoofing implementation, class index 1 is a live face;
    classes 0 and 2 are both attack classes. The specific attack type for
    indices 0 and 2 is not relied upon here.
    """

    def __init__(self):
        project_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        self.model_path = os.path.join(
            project_dir, "models", "face_anti_spoofing.onnx"
        )

        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(
                f"Anti-spoofing model not found: {self.model_path}"
            )

        self.session = ort.InferenceSession(
            self.model_path,
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

        print("Anti-spoofing engine initialized.")
        print("Model:", os.path.basename(self.model_path))

    @staticmethod
    def _prepare_face(frame, face):
        """Crop a 2.7x margin around the detected face and build NCHW input."""
        x, y, width, height = [int(round(v)) for v in face[:4]]
        image_height, image_width = frame.shape[:2]
        if width <= 0 or height <= 0:
            raise ValueError("Invalid detected face dimensions.")

        center_x = x + width / 2.0
        center_y = y + height / 2.0
        crop_width = width * 2.7
        crop_height = height * 2.7

        x1 = max(0, int(center_x - crop_width / 2.0))
        y1 = max(0, int(center_y - crop_height / 2.0))
        x2 = min(image_width, int(center_x + crop_width / 2.0))
        y2 = min(image_height, int(center_y + crop_height / 2.0))

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            raise ValueError("Could not crop the detected face.")

        crop = cv2.resize(crop, (80, 80), interpolation=cv2.INTER_LINEAR)
        tensor = crop.astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))
        return np.expand_dims(tensor, axis=0)

    def predict(self, frame, face):
        """Return probabilities for live, print attack and replay attack."""
        tensor = self._prepare_face(frame, face)
        output = self.session.run(
            [self.output_name],
            {self.input_name: tensor},
        )[0]
        values = np.asarray(output, dtype=np.float32).reshape(-1)
        if values.size != 3 or not np.all(np.isfinite(values)):
            raise ValueError("Unexpected anti-spoofing model output.")

        # The selected ONNX export already applies softmax. Do not softmax twice.
        values = np.clip(values, 0.0, 1.0)
        total = float(values.sum())
        if total <= 0.0:
            raise ValueError("Anti-spoofing model returned invalid probabilities.")
        values = values / total

        # IMPORTANT: upstream MiniFASNet uses argmax == 1 for a real/live face.
        # Class indices 0 and 2 are both spoof/attack classes.
        return {
            "live": float(values[1]),
            "attack_a": float(values[0]),
            "attack_b": float(values[2]),
        }
