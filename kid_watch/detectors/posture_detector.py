"""
KID-WATCH v0.1 — Posture Detector
MediaPipe Pose-based posture analysis
"""

import cv2
import numpy as np
import math

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from ..config import POSE_MODEL_URL, POSE_CONFIDENCE_THRESHOLD, POSTURE_ANGLE_THRESHOLD
from ..utils import download_model, draw_landmarks_on_image


class PostureDetector:
    BASELINE_EMA_ALPHA = 0.05
    EPSILON_FORWARD_LEAN = 0.001
    EPSILON_NORM = 1e-6
    SLOUCH_NECK_THRESHOLD = 145
    SLOUCH_BACK_THRESHOLD = 155

    def __init__(self, calibration_engine=None):
        model_path = download_model(POSE_MODEL_URL, "pose_landmarker.task")

        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.detector = vision.PoseLandmarker.create_from_options(options)
        self.frame_timestamp = 0

        self.face_width_baseline = None

        self.calibration_engine = calibration_engine

    def detect(self, frame_rgb, face_width=None):
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        self.frame_timestamp += 1

        detection_result = self.detector.detect_for_video(
            mp_image, self.frame_timestamp
        )

        if (
            not detection_result.pose_landmarks
            or len(detection_result.pose_landmarks) == 0
        ):
            return None, None, None

        landmarks = detection_result.pose_landmarks[0]

        LEFT_EAR = 7
        RIGHT_EAR = 8
        LEFT_SHOULDER = 11
        RIGHT_SHOULDER = 12
        LEFT_HIP = 23
        RIGHT_HIP = 24
        LEFT_KNEE = 25
        RIGHT_KNEE = 26

        left_ear = landmarks[LEFT_EAR]
        right_ear = landmarks[RIGHT_EAR]
        left_shoulder = landmarks[LEFT_SHOULDER]
        right_shoulder = landmarks[RIGHT_SHOULDER]
        left_hip = landmarks[LEFT_HIP]
        right_hip = landmarks[RIGHT_HIP]
        left_knee = landmarks[LEFT_KNEE]
        right_knee = landmarks[RIGHT_KNEE]

        if (
            left_ear.visibility < POSE_CONFIDENCE_THRESHOLD
            or right_ear.visibility < POSE_CONFIDENCE_THRESHOLD
        ):
            return None, None, detection_result

        ear = np.array([(left_ear.x + right_ear.x) / 2, (left_ear.y + right_ear.y) / 2])
        shoulder = np.array(
            [
                (left_shoulder.x + right_shoulder.x) / 2,
                (left_shoulder.y + right_shoulder.y) / 2,
            ]
        )
        hip = np.array([(left_hip.x + right_hip.x) / 2, (left_hip.y + right_hip.y) / 2])

        dx = ear[0] - shoulder[0]
        dy = shoulder[1] - ear[1]
        forward_lean = math.degrees(
            math.atan2(abs(dx), max(dy, self.EPSILON_FORWARD_LEAN))
        )

        neck_angle = self._compute_neck_angle(ear, shoulder, hip)

        back_angle = None
        knees_visible = (
            left_knee.visibility > POSE_CONFIDENCE_THRESHOLD
            and right_knee.visibility > POSE_CONFIDENCE_THRESHOLD
        )
        if knees_visible:
            knee = np.array(
                [(left_knee.x + right_knee.x) / 2, (left_knee.y + right_knee.y) / 2]
            )
            back_angle = self._compute_back_angle(shoulder, hip, knee)

        forward_head_ratio = None
        if face_width is not None:
            forward_head_ratio = self._compute_forward_head_ratio(face_width)

        is_good = self._evaluate_posture(forward_lean, neck_angle, back_angle)

        metrics = {
            "forward_lean_angle": forward_lean,
            "neck_angle": neck_angle,
            "back_angle": back_angle,
            "forward_head_ratio": forward_head_ratio,
        }

        return is_good, metrics, detection_result

    def _compute_neck_angle(self, ear, shoulder, hip):
        v1 = ear - shoulder
        v2 = hip - shoulder
        cosine_angle = np.dot(v1, v2) / (
            np.linalg.norm(v1) * np.linalg.norm(v2) + self.EPSILON_NORM
        )
        angle = np.arccos(np.clip(cosine_angle, -1.0, 1.0))
        return np.degrees(angle)

    def _compute_back_angle(self, shoulder, hip, knee):
        v1 = shoulder - hip
        v2 = knee - hip
        cosine_angle = np.dot(v1, v2) / (
            np.linalg.norm(v1) * np.linalg.norm(v2) + self.EPSILON_NORM
        )
        angle = np.arccos(np.clip(cosine_angle, -1.0, 1.0))
        return np.degrees(angle)

    def _compute_forward_head_ratio(self, current_face_width):
        if self.face_width_baseline is None:
            self.face_width_baseline = current_face_width
            return 1.0

        self.face_width_baseline = (
            self.BASELINE_EMA_ALPHA * current_face_width
            + (1 - self.BASELINE_EMA_ALPHA) * self.face_width_baseline
        )

        return current_face_width / (self.face_width_baseline + self.EPSILON_NORM)

    def _evaluate_posture(self, forward_lean, neck_angle, back_angle):
        thresholds = None
        if self.calibration_engine:
            thresholds = self.calibration_engine.get_thresholds()

        slouching = False

        if thresholds:
            if forward_lean > thresholds["forward_lean_threshold"]:
                slouching = True
            if (
                neck_angle is not None
                and neck_angle < thresholds["neck_angle_threshold"]
            ):
                slouching = True
            if (
                back_angle is not None
                and thresholds["back_angle_threshold"] is not None
                and back_angle < thresholds["back_angle_threshold"]
            ):
                slouching = True
        else:
            if forward_lean > POSTURE_ANGLE_THRESHOLD:
                slouching = True
            if neck_angle is not None and neck_angle < self.SLOUCH_NECK_THRESHOLD:
                slouching = True
            if back_angle is not None and back_angle < self.SLOUCH_BACK_THRESHOLD:
                slouching = True

        return not slouching

    def draw_skeleton(self, frame, detection_result):
        """Draw pose skeleton overlay."""
        if detection_result and detection_result.pose_landmarks:
            draw_landmarks_on_image(frame, detection_result)
