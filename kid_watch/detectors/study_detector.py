"""
KID-WATCH v0.2 — Study Detector v3
Camera-mode-aware fusion detector with compound signal (neck_flex + forward_lean)
"""

import numpy as np

from kid_watch.time_provider import RealTime


class StudyDetector:
    """
    Camera-mode-aware fusion detector that works from front and side cameras.

    Camera modes (detected from post-calibration observation window):
    - FRONT: face visible >70% of frames → use face-gaze with pose fallback
    - FRONT_NO_IRIS: face visible 30-70% → use face-gaze with pose fallback
    - SIDE: face visible <30% → use pose-only (face rarely visible)

    Detection logic:
    - FRONT: Face-gaze primary, pose fallback when face drops
    - SIDE: Pose-only with face-visibility override (face visible = NOT studying)

    Thresholds computed from calibration baseline (not hardcoded).

    v3 changes:
    - Compound signal: BOTH neck_flex AND forward_lean must agree for studying
    - Lower deltas: DELTA_ENTER_MIN=3.0°, DELTA_EXIT_MIN=2.0° (was 6.0°/4.0°)
    - Higher debounce: POSE_ENTER_FRAMES=6, POSE_EXIT_FRAMES=8 (was 3/4)
    - Post-calibration observation window for camera mode classification
    """

    # Camera modes
    FRONT = "front"
    FRONT_NO_IRIS = "front_no_iris"
    SIDE = "side"

    # Debounce frame counts (prevent rapid state flipping)
    GAZE_ENTER_FRAMES = 2  # Face-gaze: frames to enter studying
    GAZE_EXIT_FRAMES = 2  # Face-gaze: frames to exit studying
    POSE_ENTER_FRAMES = 6  # Pose: frames to enter studying (was 3)
    POSE_EXIT_FRAMES = 8  # Pose: frames to exit studying (was 4)
    FACE_HOLD_FRAMES = 8  # Hold last gaze decision after face drops
    SIDE_FACE_OVERRIDE_FRAMES = 5  # Side mode: face visible = NOT studying

    # Calibration defaults (MAD - Median Absolute Deviation)
    NECK_ANGLE_MAD_DEFAULT = 2.0  # Default MAD for neck angle if not in baseline
    MAD_MINIMUM = 1.0  # Minimum MAD to prevent division by zero
    FORWARD_LEAN_MAD_DEFAULT = 2.0  # Default MAD for forward lean if not in baseline

    # Delta thresholds for neck flexion (minimum change from baseline)
    DELTA_ENTER_MIN = 3.0  # Minimum delta to enter studying
    DELTA_EXIT_MIN = 2.0  # Minimum delta to exit studying
    K_ENTER = 3.0  # Multiplier for neck_angle_mad to compute enter delta
    K_EXIT = 2.0  # Multiplier for neck_angle_mad to compute exit delta

    # Delta thresholds for forward lean (minimum change from baseline)
    LEAN_DELTA_ENTER = 3.0  # Minimum lean delta to enter studying
    LEAN_DELTA_EXIT = 2.0  # Minimum lean delta to exit studying
    LEAN_ENTER_MULTIPLIER = 2.0  # Multiplier for lean_mad to compute enter delta
    LEAN_EXIT_MULTIPLIER = 1.5  # Multiplier for lean_mad to compute exit delta

    # Threshold offset bounds (for clamping computed thresholds)
    NECK_ENTER_MIN_OFFSET = 2.0  # Minimum offset from baseline for neck enter
    NECK_ENTER_MAX_OFFSET = 25.0  # Maximum offset from baseline for neck enter
    NECK_EXIT_MIN_OFFSET = 1.0  # Minimum offset from baseline for neck exit
    THRESHOLD_MIN_GAP = 1.0  # Minimum gap between exit and enter thresholds

    # Lean threshold offset bounds
    LEAN_ENTER_MIN_OFFSET = 2.0  # Minimum offset from baseline for lean enter
    LEAN_ENTER_MAX_OFFSET = 30.0  # Maximum offset from baseline for lean enter
    LEAN_EXIT_MIN_OFFSET = 1.0  # Minimum offset from baseline for lean exit

    # Camera mode classification thresholds (from observation window)
    OBSERVATION_WINDOW_SECONDS = 5.0  # Duration of observation window
    FRONT_MODE_FACE_RATIO = 0.70  # Face visible >70% → FRONT mode
    FRONT_NO_IRIS_FACE_RATIO = 0.30  # Face visible 30-70% → FRONT_NO_IRIS mode

    # Fallback detection threshold (when calibration not available)
    FALLBACK_NECK_FLEXION_THRESHOLD = 40  # Neck flexion threshold for fallback mode
    CONFIDENCE_THRESHOLD = 0.5  # Landmark visibility confidence threshold

    def __init__(self, calibration_engine=None, time_provider=None):
        """
        Initialize StudyDetector with optional calibration engine and time provider.

        Args:
            calibration_engine: CalibrationEngine instance (for baseline thresholds)
            time_provider: TimeProvider instance (for time queries). Defaults to RealTime().
        """
        self.calibration_engine = calibration_engine
        self._time_provider = time_provider or RealTime()

        # Camera mode and thresholds (computed lazily from calibration)
        self._camera_mode = None
        self._thresholds_computed = False
        self._neck_enter = 40.0  # Fallback defaults
        self._neck_exit = 35.0
        self._lean_enter = 20.0
        self._lean_exit = 15.0

        # Observation window state (for camera mode classification)
        self._observing = False
        self._observation_start = None
        self._observation_face_count = 0
        self._observation_total_count = 0

        # State tracking
        self._is_studying = False
        self._frame_count = 0

        # Debounce counters
        self._gaze_enter_ct = 0
        self._gaze_exit_ct = 0
        self._pose_enter_ct = 0
        self._pose_exit_ct = 0

        # Face tracking
        self._face_hold_remaining = 0
        self._face_seen_streak = 0
        self._face_miss_streak = 0

    def _compute_thresholds(self):
        """
        Compute calibrated neck flexion and forward lean thresholds from baseline.
        Called lazily once calibration completes.
        Starts observation window for camera mode classification.
        """
        if not self.calibration_engine:
            return

        baseline = self.calibration_engine.active_baseline
        if baseline is None:
            return

        neck_angle_median = baseline["neck_angle_median"]
        neck_angle_mad = max(
            baseline.get("neck_angle_mad", self.NECK_ANGLE_MAD_DEFAULT),
            self.MAD_MINIMUM,
        )

        baseline_flex = 180.0 - neck_angle_median

        enter_delta = max(self.DELTA_ENTER_MIN, self.K_ENTER * neck_angle_mad)
        exit_delta = max(self.DELTA_EXIT_MIN, self.K_EXIT * neck_angle_mad)

        self._neck_enter = baseline_flex + enter_delta
        self._neck_exit = baseline_flex + exit_delta

        self._neck_enter = max(
            self._neck_enter, baseline_flex + self.NECK_ENTER_MIN_OFFSET
        )
        self._neck_enter = min(
            self._neck_enter, baseline_flex + self.NECK_ENTER_MAX_OFFSET
        )
        self._neck_exit = max(
            self._neck_exit, baseline_flex + self.NECK_EXIT_MIN_OFFSET
        )
        self._neck_exit = min(
            self._neck_exit, self._neck_enter - self.THRESHOLD_MIN_GAP
        )

        lean_baseline = baseline["forward_lean_median"]
        lean_mad = max(
            baseline.get("forward_lean_mad", self.FORWARD_LEAN_MAD_DEFAULT),
            self.MAD_MINIMUM,
        )

        lean_enter_delta = max(
            self.LEAN_DELTA_ENTER, self.LEAN_ENTER_MULTIPLIER * lean_mad
        )
        lean_exit_delta = max(
            self.LEAN_DELTA_EXIT, self.LEAN_EXIT_MULTIPLIER * lean_mad
        )

        self._lean_enter = lean_baseline + lean_enter_delta
        self._lean_exit = lean_baseline + lean_exit_delta

        self._lean_enter = max(
            self._lean_enter, lean_baseline + self.LEAN_ENTER_MIN_OFFSET
        )
        self._lean_enter = min(
            self._lean_enter, lean_baseline + self.LEAN_ENTER_MAX_OFFSET
        )
        self._lean_exit = max(
            self._lean_exit, lean_baseline + self.LEAN_EXIT_MIN_OFFSET
        )
        self._lean_exit = min(
            self._lean_exit, self._lean_enter - self.THRESHOLD_MIN_GAP
        )

        self._observing = True
        self._observation_start = self._time_provider.now()
        self._observation_face_count = 0
        self._observation_total_count = 0
        self._thresholds_computed = True

        print(f"\n[STUDY] Thresholds computed:")
        print(
            f"  Neck flex: baseline={baseline_flex:.1f}° "
            f"enter={self._neck_enter:.1f}° exit={self._neck_exit:.1f}°"
        )
        print(
            f"  Fwd lean:  baseline={lean_baseline:.1f}° "
            f"enter={self._lean_enter:.1f}° exit={self._lean_exit:.1f}°"
        )
        print(
            f"  Debounce: pose_enter={self.POSE_ENTER_FRAMES}f "
            f"pose_exit={self.POSE_EXIT_FRAMES}f"
        )
        print(f"[STUDY] Starting 5s camera mode observation...")

    def detect(self, gaze_at_desk, pose_result, posture_metrics):
        """
        Determine if kid is studying and if person is present.

        Args:
            gaze_at_desk: bool|None from GazeDetector (None = face not detected)
            pose_result: MediaPipe pose result (from PostureDetector)
            posture_metrics: dict with neck_angle, forward_lean_angle, etc.

        Returns:
            (person_present: bool, studying: bool|None, source: str)
            - person_present: True if pose landmarks visible (regardless of face)
            - studying: True/False/None based on best available signal
            - source: "face", "pose", "pose_side", "side_face_override", "face_hold",
                      "face_fallback", "pose_fallback", "none"
        """
        self._frame_count += 1

        if not self._thresholds_computed and self.calibration_engine:
            self._compute_thresholds()

        person_present = (
            pose_result is not None
            and pose_result.pose_landmarks
            and len(pose_result.pose_landmarks) > 0
        )

        if not person_present:
            self._reset_counters()
            return False, None, "none"

        face_seen = gaze_at_desk is not None
        self._update_face_tracking(face_seen)

        neck_flexion = self._compute_neck_flexion(pose_result)

        forward_lean = (
            posture_metrics.get("forward_lean_angle") if posture_metrics else None
        )

        if not self._thresholds_computed:
            return self._detect_fallback(gaze_at_desk, neck_flexion, forward_lean)

        if self._observing:
            self._observation_total_count += 1
            if face_seen:
                self._observation_face_count += 1

            if self._observation_start is not None:
                elapsed = self._time_provider.now() - self._observation_start
                if elapsed >= self.OBSERVATION_WINDOW_SECONDS:
                    face_ratio = self._observation_face_count / max(
                        self._observation_total_count, 1
                    )
                    if face_ratio > self.FRONT_MODE_FACE_RATIO:
                        self._camera_mode = self.FRONT
                    elif face_ratio > self.FRONT_NO_IRIS_FACE_RATIO:
                        self._camera_mode = self.FRONT_NO_IRIS
                    else:
                        self._camera_mode = self.SIDE
                    self._observing = False
                    print(
                        f"[STUDY] Camera mode: {self._camera_mode} "
                        f"(face visible {face_ratio * 100:.0f}% of frames)"
                    )

            return self._detect_fallback(gaze_at_desk, neck_flexion, forward_lean)

        if self._camera_mode == self.SIDE:
            return self._detect_side(face_seen, neck_flexion, forward_lean)

        return self._detect_front(gaze_at_desk, face_seen, neck_flexion, forward_lean)

    def _detect_side(self, face_seen, neck_flexion, forward_lean):
        if self._face_seen_streak >= self.SIDE_FACE_OVERRIDE_FRAMES:
            self._is_studying = False
            self._pose_enter_ct = 0
            return True, False, "side_face_override"

        self._update_pose_state(neck_flexion, forward_lean)
        return True, self._is_studying, "pose_side"

    def _detect_front(self, gaze_at_desk, face_seen, neck_flexion, forward_lean):
        if face_seen:
            self._face_hold_remaining = self.FACE_HOLD_FRAMES
            self._update_gaze_state(gaze_at_desk)
            return True, self._is_studying, "face"

        if self._face_hold_remaining > 0:
            self._face_hold_remaining -= 1
            return True, self._is_studying, "face_hold"

        self._update_pose_state(neck_flexion, forward_lean)
        return True, self._is_studying, "pose"

    def _update_gaze_state(self, gaze_at_desk):
        if gaze_at_desk:
            self._gaze_enter_ct += 1
            self._gaze_exit_ct = 0
            if self._gaze_enter_ct >= self.GAZE_ENTER_FRAMES:
                self._is_studying = True
                self._gaze_enter_ct = 0
        else:
            self._gaze_exit_ct += 1
            self._gaze_enter_ct = 0
            if self._gaze_exit_ct >= self.GAZE_EXIT_FRAMES:
                self._is_studying = False
                self._gaze_exit_ct = 0

    def _update_pose_state(self, neck_flexion, forward_lean):
        if neck_flexion is None or forward_lean is None:
            return

        neck_studying = neck_flexion >= self._neck_enter
        lean_studying = forward_lean >= self._lean_enter
        studying_signal = neck_studying and lean_studying

        neck_not_studying = neck_flexion <= self._neck_exit
        lean_not_studying = forward_lean <= self._lean_exit
        not_studying_signal = neck_not_studying or lean_not_studying

        if not self._is_studying:
            if studying_signal:
                self._pose_enter_ct += 1
            else:
                self._pose_enter_ct = 0

            if self._pose_enter_ct >= self.POSE_ENTER_FRAMES:
                self._is_studying = True
                self._pose_enter_ct = 0
        else:
            if not_studying_signal:
                self._pose_exit_ct += 1
            else:
                self._pose_exit_ct = 0

            if self._pose_exit_ct >= self.POSE_EXIT_FRAMES:
                self._is_studying = False
                self._pose_exit_ct = 0

    def _update_face_tracking(self, face_seen):
        if face_seen:
            self._face_seen_streak += 1
            self._face_miss_streak = 0
        else:
            self._face_miss_streak += 1
            self._face_seen_streak = 0

    def _detect_fallback(self, gaze_at_desk, neck_flexion, forward_lean):
        if gaze_at_desk is not None:
            return True, gaze_at_desk, "face_fallback"

        if (
            neck_flexion is not None
            and neck_flexion > self.FALLBACK_NECK_FLEXION_THRESHOLD
        ):
            return True, True, "pose_fallback"

        return True, False, "pose_fallback"

    def _reset_counters(self):
        self._gaze_enter_ct = 0
        self._gaze_exit_ct = 0
        self._pose_enter_ct = 0
        self._pose_exit_ct = 0
        self._face_hold_remaining = 0
        self._face_seen_streak = 0
        self._face_miss_streak = 0

    def _compute_neck_flexion(self, pose_result):
        landmarks = pose_result.pose_landmarks[0]

        # Get landmarks
        left_ear = landmarks[7]
        right_ear = landmarks[8]
        left_shoulder = landmarks[11]
        right_shoulder = landmarks[12]
        left_hip = landmarks[23]
        right_hip = landmarks[24]

        # Pick best visible ear
        if (
            left_ear.visibility > self.CONFIDENCE_THRESHOLD
            and right_ear.visibility > self.CONFIDENCE_THRESHOLD
        ):
            head_x = (left_ear.x + right_ear.x) / 2
            head_y = (left_ear.y + right_ear.y) / 2
        elif left_ear.visibility > self.CONFIDENCE_THRESHOLD:
            head_x = left_ear.x
            head_y = left_ear.y
        elif right_ear.visibility > self.CONFIDENCE_THRESHOLD:
            head_x = right_ear.x
            head_y = right_ear.y
        else:
            # Try nose as fallback
            nose = landmarks[0]
            if nose.visibility > self.CONFIDENCE_THRESHOLD:
                head_x = nose.x
                head_y = nose.y
            else:
                return None  # Can't determine head position

        # Shoulder midpoint
        shoulder_x = (left_shoulder.x + right_shoulder.x) / 2
        shoulder_y = (left_shoulder.y + right_shoulder.y) / 2

        # Hip midpoint (for torso axis)
        hips_visible = (
            left_hip.visibility > self.CONFIDENCE_THRESHOLD
            and right_hip.visibility > self.CONFIDENCE_THRESHOLD
        )

        if hips_visible:
            hip_x = (left_hip.x + right_hip.x) / 2
            hip_y = (left_hip.y + right_hip.y) / 2

            # Torso-up vector (from hip to shoulder)
            torso_dx = shoulder_x - hip_x
            torso_dy = (
                shoulder_y - hip_y
            )  # Note: Y is inverted in image coords (up = negative)
            torso_len = np.sqrt(torso_dx**2 + torso_dy**2) + 1e-6
            torso_ux = torso_dx / torso_len
            torso_uy = torso_dy / torso_len
        else:
            # Fallback: assume torso is vertical (less robust but works)
            torso_ux = 0
            torso_uy = -1  # Straight up in image coords

        # Head vector (from shoulder to head)
        head_dx = head_x - shoulder_x
        head_dy = head_y - shoulder_y
        head_len = np.sqrt(head_dx**2 + head_dy**2) + 1e-6
        head_ux = head_dx / head_len
        head_uy = head_dy / head_len

        # Angle between torso-up and head vector
        dot = torso_ux * head_ux + torso_uy * head_uy
        dot = np.clip(dot, -1.0, 1.0)
        angle_rad = np.arccos(dot)
        angle_deg = np.degrees(angle_rad)

        return float(angle_deg)
