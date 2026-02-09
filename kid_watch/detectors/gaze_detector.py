"""
KID-WATCH v0.1 — Gaze Detector
MediaPipe Face Landmarker-based gaze estimation
"""

import numpy as np

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from ..config import FACE_MODEL_URL, GAZE_DOWN_PITCH_THRESHOLD, GAZE_AWAY_YAW_THRESHOLD
from ..utils import download_model, calculate_distance


class GazeDetector:
    # Magic number constants
    PITCH_SCALE_FACTOR = 45
    YAW_SCALE_FACTOR = 45
    MIN_INTER_OCULAR_DISTANCE = 30
    IRIS_RATIO_AVERAGE_DIVISOR = 2.0
    EPSILON = 1e-6

    def __init__(self, calibration_engine=None):
        model_path = download_model(FACE_MODEL_URL, "face_landmarker.task")

        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self.detector = vision.FaceLandmarker.create_from_options(options)
        self.frame_timestamp = 0

        self.calibration_engine = calibration_engine

    def detect(self, frame_rgb):
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        self.frame_timestamp += 1

        detection_result = self.detector.detect_for_video(
            mp_image, self.frame_timestamp
        )

        if (
            not detection_result.face_landmarks
            or len(detection_result.face_landmarks) == 0
        ):
            return None, None, None, None, None

        face_landmarks = detection_result.face_landmarks[0]
        h, w = frame_rgb.shape[:2]

        # Head pose estimation (existing logic)
        nose_tip = face_landmarks[1]
        chin = face_landmarks[152]
        left_eye_outer = face_landmarks[33]  # Left eye outer corner
        right_eye_outer = face_landmarks[263]  # Right eye outer corner

        nose_2d = np.array([nose_tip.x * w, nose_tip.y * h])
        chin_2d = np.array([chin.x * w, chin.y * h])
        left_eye_2d = np.array([left_eye_outer.x * w, left_eye_outer.y * h])
        right_eye_2d = np.array([right_eye_outer.x * w, right_eye_outer.y * h])

        eye_center = (left_eye_2d + right_eye_2d) / 2
        vertical_dist = chin_2d[1] - eye_center[1]
        nose_vertical_offset = nose_2d[1] - eye_center[1]
        pitch = (
            nose_vertical_offset / (vertical_dist + self.EPSILON)
        ) * self.PITCH_SCALE_FACTOR

        eye_width = calculate_distance(left_eye_2d, right_eye_2d)
        nose_horizontal_offset = nose_2d[0] - eye_center[0]
        yaw = (
            nose_horizontal_offset / (eye_width + self.EPSILON)
        ) * self.YAW_SCALE_FACTOR

        # === IRIS TRACKING (NEW) ===
        # Iris landmarks: right iris center=468, left iris center=473
        # Eye boundary landmarks: L_top=159, L_bottom=145, R_top=386, R_bottom=374

        inter_ocular_distance = eye_width

        if inter_ocular_distance < self.MIN_INTER_OCULAR_DISTANCE:
            iris_ratio = None
            is_looking_at_desk = pitch > GAZE_DOWN_PITCH_THRESHOLD
        else:
            right_iris_center = face_landmarks[468]
            left_iris_center = face_landmarks[473]

            left_eye_top = face_landmarks[159]
            left_eye_bottom = face_landmarks[145]
            right_eye_top = face_landmarks[386]
            right_eye_bottom = face_landmarks[374]

            left_eye_height = left_eye_bottom.y - left_eye_top.y
            right_eye_height = right_eye_bottom.y - right_eye_top.y

            left_iris_ratio = (left_iris_center.y - left_eye_top.y) / (
                left_eye_height + self.EPSILON
            )
            right_iris_ratio = (right_iris_center.y - right_eye_top.y) / (
                right_eye_height + self.EPSILON
            )

            iris_ratio = (
                left_iris_ratio + right_iris_ratio
            ) / self.IRIS_RATIO_AVERAGE_DIVISOR

        thresholds = None
        if self.calibration_engine:
            thresholds = self.calibration_engine.get_thresholds()

        iris_threshold = thresholds.get("iris_ratio_threshold") if thresholds else None

        if iris_threshold is not None and iris_ratio is not None:
            is_looking_at_desk = (
                pitch > GAZE_DOWN_PITCH_THRESHOLD and iris_ratio > iris_threshold
            )
        else:
            is_looking_at_desk = pitch > GAZE_DOWN_PITCH_THRESHOLD

        return is_looking_at_desk, pitch, yaw, iris_ratio, eye_width
