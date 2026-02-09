"""
KID-WATCH v0.3 — YOLO Pose Detector

COCO keypoint indices used: LEar(3), REar(4), LShoulder(5), RShoulder(6),
LHip(11), RHip(12), LKnee(13), RKnee(14)
"""

import logging
import math
import statistics
import time
from collections import deque

import numpy as np
from ultralytics import YOLO

from ..config import POSE_CONFIDENCE_THRESHOLD, POSTURE_ANGLE_THRESHOLD
from ..time_provider import RealTime

logger = logging.getLogger(__name__)

LEAR = 3
REAR = 4
LSHOULDER = 5
RSHOULDER = 6
LHIP = 11
RHIP = 12
LKNEE = 13
RKNEE = 14

MIN_VISIBLE_KEYPOINTS = 7
DEFAULT_KP_CONFIDENCE = 0.3


class YoloPoseDetector:
    """Drop-in replacement for PostureDetector using YOLOv8n-pose."""

    # EMA smoothing for face width baseline
    BASELINE_EMA_ALPHA = 0.05

    # Forward lean buffer size for median filtering
    FORWARD_LEAN_BUFFER_SIZE = 5

    # Time-based posture hysteresis thresholds (seconds)
    SLOUCH_ENTER_SECONDS = 1.0
    SLOUCH_EXIT_SECONDS = 0.6

    # Last-value hold duration when detection fails (seconds)
    HOLD_DURATION_SECONDS = 0.5

    # Fallback mode logging interval (seconds)
    FALLBACK_LOG_INTERVAL = 2.0

    # Posture angle thresholds (degrees)
    SLOUCH_NECK_THRESHOLD = 145
    SLOUCH_BACK_THRESHOLD = 155

    # Numeric epsilon for vector calculations
    EPSILON = 1e-6

    def __init__(
        self,
        calibration_engine=None,
        kp_confidence: float = DEFAULT_KP_CONFIDENCE,
        time_provider=None,
    ):
        logger.info("[POSTURE-YOLO] Loading YOLOv8n-pose model...")
        self.model = YOLO("yolov8n-pose.pt")
        self.calibration_engine = calibration_engine
        self.kp_confidence = kp_confidence
        self.face_width_baseline: float | None = None
        self.baseline_alpha = self.BASELINE_EMA_ALPHA
        self._time_provider = time_provider or RealTime()

        # Fix A: 5-frame median filter on forward_lean
        self._forward_lean_buffer = deque(maxlen=self.FORWARD_LEAN_BUFFER_SIZE)

        # Fix B: Time-based posture hysteresis
        self._posture_state = True  # Current hysteresis state (True=good, False=bad)
        self._posture_change_start = None  # When raw evaluation started disagreeing
        self._slouch_enter_time = (
            self.SLOUCH_ENTER_SECONDS
        )  # seconds of bad posture to enter slouching
        self._slouch_exit_time = (
            self.SLOUCH_EXIT_SECONDS
        )  # seconds of good posture to exit slouching

        # Fix C: Last-value hold when detection fails
        self._last_valid_posture = None  # Last (posture_good, posture_metrics)
        self._last_valid_time = 0.0  # When last valid result was produced
        self._hold_duration = self.HOLD_DURATION_SECONDS  # seconds to hold last value

        # Fallback mode logging throttle
        self._last_fallback_log_time = 0.0

    def detect(self, frame_rgb, face_width=None):
        """
        Returns: (is_good, metrics, raw_result) — same 3-tuple as PostureDetector.
        is_good: bool|None, metrics: dict|None, raw_result: ultralytics Results|None
        """
        t0 = time.perf_counter()
        results = self.model(frame_rgb, verbose=False)
        dt_ms = (time.perf_counter() - t0) * 1000
        logger.debug("[POSTURE-YOLO] Inference %.1fms", dt_ms)

        if not results or len(results) == 0:
            return None, None, None

        result = results[0]

        if result.keypoints is None or result.keypoints.data.shape[0] == 0:
            return None, None, result

        person_idx = self._select_largest_person(result)
        kp_data = result.keypoints.data[person_idx].cpu().numpy()

        confidences = kp_data[:, 2]
        visible_count = int(np.sum(confidences > self.kp_confidence))
        if visible_count < MIN_VISIBLE_KEYPOINTS:
            logger.debug(
                "[POSTURE-YOLO] Insufficient keypoints: %d/%d visible (need %d)",
                visible_count,
                17,
                MIN_VISIBLE_KEYPOINTS,
            )
            return None, None, result

        shoulder = self._midpoint_or_visible(kp_data, LSHOULDER, RSHOULDER)
        hip = self._midpoint_or_visible(kp_data, LHIP, RHIP)

        if shoulder is None or hip is None:
            if (
                self._last_valid_posture is not None
                and self._time_provider.now() - self._last_valid_time
                <= self._hold_duration
            ):
                return self._last_valid_posture + (result,)
            return None, None, result

        ears_available = (
            confidences[LEAR] >= self.kp_confidence
            or confidences[REAR] >= self.kp_confidence
        )
        ear = None
        if ears_available:
            ear = self._midpoint_or_visible(kp_data, LEAR, REAR)

        if ear is not None:
            dx = ear[0] - shoulder[0]
            dy = shoulder[1] - ear[1]
            forward_lean = math.degrees(math.atan2(abs(dx), max(dy, self.EPSILON)))

            self._forward_lean_buffer.append(forward_lean)
            smoothed_forward_lean = statistics.median(self._forward_lean_buffer)

            neck_angle = self._vector_angle(ear, shoulder, hip)

            back_angle = None
            knee = self._midpoint_or_visible(kp_data, LKNEE, RKNEE)
            if knee is not None:
                back_angle = self._vector_angle(shoulder, hip, knee)

            posture_source = "ear"
        else:
            current_time = self._time_provider.now()
            if (
                current_time - self._last_fallback_log_time
                >= self.FALLBACK_LOG_INTERVAL
            ):
                print("[POSTURE] mode=shoulder_hip (ears not visible)")
                self._last_fallback_log_time = current_time

            dx = shoulder[0] - hip[0]
            dy = hip[1] - shoulder[1]
            forward_lean = math.degrees(math.atan2(abs(dx), max(dy, self.EPSILON)))

            self._forward_lean_buffer.append(forward_lean)
            smoothed_forward_lean = statistics.median(self._forward_lean_buffer)

            neck_angle = None

            back_angle = None
            knee = self._midpoint_or_visible(kp_data, LKNEE, RKNEE)
            if knee is not None:
                back_angle = self._vector_angle(shoulder, hip, knee)

            posture_source = "shoulder_hip"

        forward_head_ratio = None
        if face_width is not None:
            forward_head_ratio = self._compute_forward_head_ratio(face_width)

        raw_good = self._evaluate_posture(smoothed_forward_lean, neck_angle, back_angle)

        if raw_good != self._posture_state:
            if self._posture_change_start is None:
                self._posture_change_start = self._time_provider.now()
            else:
                elapsed = self._time_provider.now() - self._posture_change_start
                required = (
                    self._slouch_exit_time if raw_good else self._slouch_enter_time
                )
                if elapsed >= required:
                    self._posture_state = raw_good
                    self._posture_change_start = None
        else:
            self._posture_change_start = None

        posture_good = self._posture_state

        metrics = {
            "forward_lean_angle": forward_lean,
            "forward_lean_smoothed": smoothed_forward_lean,
            "neck_angle": neck_angle,
            "back_angle": back_angle,
            "forward_head_ratio": forward_head_ratio,
            "posture_source": posture_source,
        }

        self._last_valid_posture = (posture_good, metrics)
        self._last_valid_time = self._time_provider.now()

        return posture_good, metrics, result

    def _select_largest_person(self, result) -> int:
        if result.boxes is None or len(result.boxes) == 0:
            return 0
        boxes = result.boxes.xyxy.cpu().numpy()
        areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        return int(np.argmax(areas))

    def _midpoint_or_visible(
        self, kp_data: np.ndarray, idx_left: int, idx_right: int
    ) -> np.ndarray | None:
        """Return midpoint if both visible, single visible point, or None."""
        left_ok = kp_data[idx_left, 2] > self.kp_confidence
        right_ok = kp_data[idx_right, 2] > self.kp_confidence

        if left_ok and right_ok:
            return (kp_data[idx_left, :2] + kp_data[idx_right, :2]) / 2.0
        if left_ok:
            return kp_data[idx_left, :2].copy()
        if right_ok:
            return kp_data[idx_right, :2].copy()
        return None

    def _vector_angle(self, a: np.ndarray, vertex: np.ndarray, b: np.ndarray) -> float:
        """Angle at vertex between rays vertex→a and vertex→b, in degrees."""
        v1 = a - vertex
        v2 = b - vertex
        cos_angle = np.dot(v1, v2) / (
            np.linalg.norm(v1) * np.linalg.norm(v2) + self.EPSILON
        )
        angle = np.arccos(np.clip(cos_angle, -1.0, 1.0))
        return float(np.degrees(angle))

    def _compute_forward_head_ratio(self, current_face_width: float) -> float:
        if self.face_width_baseline is None:
            self.face_width_baseline = current_face_width
            return 1.0

        self.face_width_baseline = (
            self.baseline_alpha * current_face_width
            + (1 - self.baseline_alpha) * self.face_width_baseline
        )
        return current_face_width / (self.face_width_baseline + self.EPSILON)

    def _evaluate_posture(
        self,
        forward_lean: float,
        neck_angle: float | None,
        back_angle: float | None,
    ) -> bool:
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
