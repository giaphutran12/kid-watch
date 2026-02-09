"""
KID-WATCH v0.3 — Calibration Engine
Zero-touch auto-calibration using COCO 17-keypoint space (YOLOv8n-pose)
"""

import numpy as np

from kid_watch.time_provider import RealTime


class CalibrationEngine:
    """Zero-touch auto-calibration from COCO keypoints (no FaceLandmarker)."""

    CALIBRATION_DURATION = 10
    MAX_BASELINES = 3
    POSITION_CHANGE_THRESHOLD = 0.25
    POSITION_CHANGE_DURATION = 2.0
    MIN_SAMPLES_FOR_CALIBRATION = 30
    MAX_CALIBRATION_TIMEOUT = 45

    WAITING_TIMEOUT = 60
    GOOD_POSTURE_NECK_THRESHOLD = 148
    GOOD_POSTURE_LEAN_THRESHOLD = 23
    GOOD_POSTURE_SUSTAIN = 1.0
    BAD_POSTURE_GRACE = 2.0

    # Position change detection (for YOLO pixel coordinates)
    FRAME_WIDTH = 1280
    FRAME_HEIGHT = 720
    POSITION_CHANGE_X_THRESHOLD = 0.10  # 10% of frame width (~128px)
    POSITION_CHANGE_Y_THRESHOLD = 0.08  # 8% of frame height (~58px)
    POSITION_CHANGE_CONSECUTIVE_FRAMES = 15  # Require 15 consecutive frames
    CALIBRATION_COOLDOWN_SECONDS = 10.0  # 10 second cooldown after calibration
    SLOUCH_GATE_THRESHOLD = (
        8.0  # degrees above baseline forward_lean to gate position changes
    )

    # Body rotation detection (shoulder width change)
    ROTATION_WIDTH_CHANGE_THRESHOLD = 0.30  # 30% change in shoulder width
    ROTATION_CONSECUTIVE_FRAMES = 30  # ~2 seconds at 15 FPS

    # Neutral posture settle phase (for calibration)
    NEUTRAL_SETTLE_SECONDS = 1.0
    # Neutral forward lean threshold
    NEUTRAL_SETTLE_LEAN_THRESHOLD = 23.0
    # Neck angle valid range
    NECK_ANGLE_VALID_MIN = 100
    NECK_ANGLE_VALID_MAX = 180
    # Back angle valid range
    BACK_ANGLE_VALID_MIN = 80
    BACK_ANGLE_VALID_MAX = 180
    # Forward lean valid range
    FORWARD_LEAN_VALID_MIN = 0
    FORWARD_LEAN_VALID_MAX = 60
    # Minimum absolute samples for calibration
    MIN_ABSOLUTE_SAMPLES = 10
    # MAD multiplier for threshold calculation (≈2σ equivalent)
    MAD_MULTIPLIER = 2.5
    # MAD floor values for robust threshold calculation
    NECK_ANGLE_MAD_FLOOR = 5.0
    BACK_ANGLE_MAD_FLOOR = 5.0
    FORWARD_LEAN_MAD_FLOOR = 6.0
    # Centroid normalization factor
    CENTROID_NORMALIZATION = 100.0
    # Baseline match threshold
    BASELINE_MATCH_THRESHOLD = 0.15
    # Shoulder confidence threshold
    SHOULDER_CONFIDENCE_THRESHOLD = 0.3

    def __init__(self, time_provider=None):
        self._time_provider = time_provider or RealTime()

        self.state = "waiting"
        self.baselines = []
        self.active_baseline = None
        self.calibration_samples = []
        self.calibration_start_time = None

        self.last_stable_pose_centroid = None
        self.last_stable_hip_centroid = None
        self.position_change_start = None

        self.waiting_start_time = self._time_provider.now()
        self.good_posture_start = None
        self.bad_posture_start = None
        self.best_observed_window = None
        self.best_observed_neck_angle = 0
        self.calibration_good_samples = 0

        # Position change consecutive frame counter
        self._position_change_consecutive = 0
        # Post-calibration cooldown timestamp
        self._calibration_cooldown_until = 0.0
        # Neutral posture settle phase (for calibration)
        self._neutral_settle_start = None

        # Body rotation detection state
        self.calibrated_shoulder_width = None
        self._rotation_consecutive = 0

        # Person-absent tracking during calibration
        self._no_person_start = None
        self.NO_PERSON_ABORT_SECONDS = 3.0

        # Throttle "Calibration extended" log spam
        self._last_extended_log_time = 0
        self.EXTENDED_LOG_INTERVAL = 5.0

        # Throttle finalize attempts to once per second
        self._last_finalize_attempt_time = 0
        self.FINALIZE_ATTEMPT_INTERVAL = 1.0

        self._debug_frames_total = 0
        self._debug_frames_pose_ok = 0
        self._debug_add_sample_called = 0
        self._debug_samples_accepted = 0
        self._debug_reject_no_posture = 0
        self._debug_reject_no_neck_fwd = 0
        self._debug_reject_neck_range = 0
        self._debug_reject_back_range = 0
        self._debug_reject_fwd_lean_range = 0
        self._debug_last_log_time = 0

    def start_calibration(self):
        self.state = "waiting"
        self.waiting_start_time = self._time_provider.now()
        self.good_posture_start = None
        self.best_observed_window = None
        self.best_observed_neck_angle = 0
        self.calibration_samples = []
        self.calibration_start_time = None
        self.position_change_start = None
        self.last_stable_hip_centroid = None
        self._no_person_start = None
        self._last_finalize_attempt_time = 0
        self._debug_frames_total = 0
        self._debug_frames_pose_ok = 0
        self._debug_add_sample_called = 0
        self._debug_samples_accepted = 0
        self._debug_reject_no_posture = 0
        self._debug_reject_no_neck_fwd = 0
        self._debug_reject_neck_range = 0
        self._debug_reject_back_range = 0
        self._debug_reject_fwd_lean_range = 0
        self._debug_last_log_time = 0

    def check_good_posture(self, posture_metrics):
        if posture_metrics is None:
            return False
        neck_angle = posture_metrics.get("neck_angle")
        forward_lean = posture_metrics.get("forward_lean_angle")
        if neck_angle is None or forward_lean is None:
            return False
        return (
            neck_angle > self.GOOD_POSTURE_NECK_THRESHOLD
            and forward_lean < self.GOOD_POSTURE_LEAN_THRESHOLD
        )

    def update_waiting_state(self, posture_metrics):
        current_time = self._time_provider.now()
        elapsed_waiting = current_time - self.waiting_start_time

        if posture_metrics:
            neck = posture_metrics.get("neck_angle")
            if neck is not None and neck > self.best_observed_neck_angle:
                self.best_observed_neck_angle = neck
                self.best_observed_window = current_time

        if elapsed_waiting >= self.WAITING_TIMEOUT:
            print(
                f"\n[CAL] Waiting timeout ({elapsed_waiting:.0f}s), force-starting calibration"
            )
            self._start_calibrating()
            return True, "Timeout - starting calibration"

        is_good = self.check_good_posture(posture_metrics)

        if is_good:
            if self.good_posture_start is None:
                self.good_posture_start = current_time

            sustained = current_time - self.good_posture_start
            if sustained >= self.GOOD_POSTURE_SUSTAIN:
                print(
                    f"\n[CAL] Good posture detected for {sustained:.1f}s, starting calibration!"
                )
                self._start_calibrating()
                return True, "Good posture detected"
        else:
            self.good_posture_start = None

        return False, None

    def _start_calibrating(self):
        self.state = "calibrating"
        self.calibration_samples = []
        self.calibration_start_time = self._time_provider.now()
        self.bad_posture_start = None
        self.position_change_start = None
        self._neutral_settle_start = None
        self._no_person_start = None
        self._debug_frames_total = 0
        self._debug_frames_pose_ok = 0
        self._debug_add_sample_called = 0
        self._debug_samples_accepted = 0
        self._debug_reject_no_posture = 0
        self._debug_reject_no_neck_fwd = 0
        self._debug_reject_neck_range = 0
        self._debug_reject_back_range = 0
        self._debug_reject_fwd_lean_range = 0
        self._debug_last_log_time = 0

    def mark_person_absent(self):
        """Called each frame when no person is detected during calibration.
        After NO_PERSON_ABORT_SECONDS, aborts calibration to 'waiting' state."""
        if self.state not in ["calibrating", "recalibrating"]:
            return

        if self._no_person_start is None:
            self._no_person_start = self._time_provider.now()

        elapsed = self._time_provider.now() - self._no_person_start
        if elapsed >= self.NO_PERSON_ABORT_SECONDS:
            print(
                f"\n[CAL] No person detected for {elapsed:.1f}s during calibration, switching to waiting"
            )
            self.state = "waiting"
            self.waiting_start_time = self._time_provider.now()
            self.good_posture_start = None
            self.calibration_samples = []
            self._no_person_start = None

    def add_sample(self, posture_metrics, pose_centroid, shoulder_width=None):
        if self.state not in ["calibrating", "recalibrating"]:
            return False

        self._no_person_start = None
        self._debug_add_sample_called += 1

        if posture_metrics is None:
            self._debug_reject_no_posture += 1
            return False

        neck_angle = posture_metrics.get("neck_angle")
        back_angle = posture_metrics.get("back_angle")
        forward_lean = posture_metrics.get("forward_lean_angle")

        if neck_angle is None or forward_lean is None:
            self._debug_reject_no_neck_fwd += 1
            return False

        if forward_lean < self.NEUTRAL_SETTLE_LEAN_THRESHOLD:
            if self._neutral_settle_start is None:
                self._neutral_settle_start = self._time_provider.now()
            elif (
                self._time_provider.now() - self._neutral_settle_start
                < self.NEUTRAL_SETTLE_SECONDS
            ):
                return False
        else:
            self._neutral_settle_start = None
            return False

        if not (self.NECK_ANGLE_VALID_MIN <= neck_angle <= self.NECK_ANGLE_VALID_MAX):
            self._debug_reject_neck_range += 1
            return False

        clean_back_angle = back_angle
        if back_angle is not None and not (
            self.BACK_ANGLE_VALID_MIN <= back_angle <= self.BACK_ANGLE_VALID_MAX
        ):
            clean_back_angle = None
            self._debug_reject_back_range += 1

        if not (
            self.FORWARD_LEAN_VALID_MIN <= forward_lean <= self.FORWARD_LEAN_VALID_MAX
        ):
            self._debug_reject_fwd_lean_range += 1
            return False

        if not self.check_good_posture(posture_metrics):
            current_time = self._time_provider.now()
            if self.bad_posture_start is None:
                self.bad_posture_start = current_time
            elif current_time - self.bad_posture_start > self.BAD_POSTURE_GRACE:
                print(
                    f"\n[CAL] Bad posture during calibration for >{self.BAD_POSTURE_GRACE}s, resetting to waiting"
                )
                self.state = "waiting"
                self.waiting_start_time = self._time_provider.now()
                self.good_posture_start = None
                self.calibration_samples = []
                return False
            return False
        else:
            self.bad_posture_start = None

        sample = {
            "neck_angle": neck_angle,
            "back_angle": clean_back_angle,
            "forward_lean_angle": forward_lean,
            "pose_centroid": pose_centroid,
            "shoulder_width": shoulder_width,
            "timestamp": self._time_provider.now(),
        }
        self.calibration_samples.append(sample)
        self._debug_samples_accepted += 1
        return True

    def _debug_log_calibration_stats(self):
        now = self._time_provider.now()
        if now - self._debug_last_log_time < 1.0:
            return
        self._debug_last_log_time = now
        elapsed = (
            now - self.calibration_start_time if self.calibration_start_time else 0
        )
        total = self._debug_frames_total or 1
        print(
            f"\n[CAL DEBUG] {elapsed:.1f}s | "
            f"frames={self._debug_frames_total} pose_ok={self._debug_frames_pose_ok}({self._debug_frames_pose_ok * 100 // total}%) "
            f"called={self._debug_add_sample_called} accepted={self._debug_samples_accepted} | "
            f"REJECTS: no_posture={self._debug_reject_no_posture} no_neck_fwd={self._debug_reject_no_neck_fwd} "
            f"neck={self._debug_reject_neck_range} back={self._debug_reject_back_range} "
            f"fwd_lean={self._debug_reject_fwd_lean_range}"
        )

    def finalize_calibration(self):
        elapsed = (
            self._time_provider.now() - self.calibration_start_time
            if self.calibration_start_time
            else 0
        )
        num_samples = len(self.calibration_samples)
        print(
            f"\n[CAL FINALIZE] samples={num_samples}/{self.MIN_SAMPLES_FOR_CALIBRATION} "
            f"elapsed={elapsed:.1f}s "
            f"rate={num_samples / (elapsed + 0.001):.1f}/s"
        )

        timeout_exceeded = elapsed >= self.MAX_CALIBRATION_TIMEOUT

        if num_samples < self.MIN_SAMPLES_FOR_CALIBRATION:
            if timeout_exceeded and num_samples >= self.MIN_ABSOLUTE_SAMPLES:
                print(
                    f"[CAL WARN] Timeout exceeded ({elapsed:.1f}s), force-finalizing with {num_samples} samples"
                )
            elif timeout_exceeded:
                print(
                    f"[CAL ERROR] Timeout exceeded but only {num_samples} samples (need {self.MIN_ABSOLUTE_SAMPLES}), switching to active with hardcoded defaults"
                )
                self.state = "active"
                self.active_baseline = None
                return True
            else:
                return False

        neck_angles = [s["neck_angle"] for s in self.calibration_samples]
        back_angles = [
            s["back_angle"]
            for s in self.calibration_samples
            if s["back_angle"] is not None
        ]
        forward_leans = [s["forward_lean_angle"] for s in self.calibration_samples]

        baseline = {
            "neck_angle_median": float(np.median(neck_angles)),
            "neck_angle_mad": float(
                np.median(np.abs(neck_angles - np.median(neck_angles)))
            ),
            "forward_lean_median": float(np.median(forward_leans)),
            "forward_lean_mad": float(
                np.median(np.abs(forward_leans - np.median(forward_leans)))
            ),
            "timestamp": self._time_provider.now(),
        }

        if len(back_angles) >= self.MIN_SAMPLES_FOR_CALIBRATION // 2:
            baseline["back_angle_median"] = float(np.median(back_angles))
            baseline["back_angle_mad"] = float(
                np.median(np.abs(back_angles - np.median(back_angles)))
            )
            baseline["has_back_angle"] = True
        else:
            baseline["has_back_angle"] = False

        centroids = [s["pose_centroid"] for s in self.calibration_samples]
        baseline["pose_centroid_x"] = float(np.median([c[0] for c in centroids]))
        baseline["pose_centroid_y"] = float(np.median([c[1] for c in centroids]))

        shoulder_widths = []
        for sample in self.calibration_samples:
            if "shoulder_width" in sample and sample["shoulder_width"] is not None:
                shoulder_widths.append(sample["shoulder_width"])

        if len(shoulder_widths) >= self.MIN_SAMPLES_FOR_CALIBRATION // 2:
            baseline["shoulder_width"] = float(np.median(shoulder_widths))

        self.baselines.append(baseline)
        if len(self.baselines) > self.MAX_BASELINES:
            self.baselines.pop(0)

        self.active_baseline = baseline
        self.last_stable_pose_centroid = np.array(
            [baseline["pose_centroid_x"], baseline["pose_centroid_y"]]
        )

        if "shoulder_width" in baseline:
            self.calibrated_shoulder_width = baseline["shoulder_width"]
        else:
            self.calibrated_shoulder_width = None

        self.calibration_samples = []
        self.state = "active"
        self._calibration_cooldown_until = (
            self._time_provider.now() + self.CALIBRATION_COOLDOWN_SECONDS
        )

        return True

    def check_calibration_progress(self):
        if self.state == "waiting":
            return -1.0, False

        if self.state not in ["calibrating", "recalibrating"]:
            return 1.0, False

        if self.calibration_start_time is None:
            return 0.0, False

        elapsed = self._time_provider.now() - self.calibration_start_time
        progress = min(elapsed / self.CALIBRATION_DURATION, 1.0)

        should_finalize = elapsed >= self.CALIBRATION_DURATION

        # Throttle finalize attempts to once per second (prevents log spam)
        if should_finalize:
            now = self._time_provider.now()
            if now - self._last_finalize_attempt_time < self.FINALIZE_ATTEMPT_INTERVAL:
                should_finalize = False
            else:
                self._last_finalize_attempt_time = now

        return progress, should_finalize

    def check_position_change(
        self, pose_centroid, hip_centroid=None, forward_lean=None
    ):
        if self.state != "active":
            return False

        if self.last_stable_pose_centroid is None:
            return False

        if pose_centroid is None:
            return False

        if self._time_provider.now() < self._calibration_cooldown_until:
            return False

        # Initialize hip baseline on first call after calibration (if hip data available)
        if hip_centroid is not None and self.last_stable_hip_centroid is None:
            self.last_stable_hip_centroid = (
                hip_centroid.copy() if hasattr(hip_centroid, "copy") else hip_centroid
            )
            return False

        if (
            forward_lean is not None
            and self.active_baseline is not None
            and "forward_lean_median" in self.active_baseline
        ):
            baseline_fwd_lean = self.active_baseline["forward_lean_median"]
            if forward_lean > baseline_fwd_lean + self.SLOUCH_GATE_THRESHOLD:
                self._position_change_consecutive = 0
                return False

        # Only compare hip-to-hip. If hip data unavailable, skip this frame
        # (shoulder fallback caused false recalibrations due to offset differences)
        if hip_centroid is not None and self.last_stable_hip_centroid is not None:
            tracking_point = hip_centroid
            baseline_point = self.last_stable_hip_centroid
            tracking_mode = "hip"
        else:
            # No hip data — skip position check this frame rather than
            # falling back to shoulder (which has different offset and causes jitter)
            self._position_change_consecutive = 0
            return False

        x_distance = abs(tracking_point[0] - baseline_point[0])
        y_distance = abs(tracking_point[1] - baseline_point[1])

        x_change = x_distance / self.FRAME_WIDTH
        y_change = y_distance / self.FRAME_HEIGHT

        position_changed = (
            x_change > self.POSITION_CHANGE_X_THRESHOLD
            or y_change > self.POSITION_CHANGE_Y_THRESHOLD
        )

        if position_changed:
            self._position_change_consecutive += 1
            print(
                f"[CAL POS] tracking={tracking_mode} x_change={x_change:.4f} y_change={y_change:.4f} "
                f"consecutive={self._position_change_consecutive}/{self.POSITION_CHANGE_CONSECUTIVE_FRAMES}"
            )
            if (
                self._position_change_consecutive
                >= self.POSITION_CHANGE_CONSECUTIVE_FRAMES
            ):
                self._position_change_consecutive = 0
                return True
        else:
            self._position_change_consecutive = 0

        return False

    def check_body_rotation(self, yolo_result):
        if self.state != "active":
            return False

        if self.calibrated_shoulder_width is None:
            return False

        if yolo_result is None or not hasattr(yolo_result, "keypoints"):
            return False

        if yolo_result.keypoints is None or len(yolo_result.keypoints.data) == 0:
            return False

        if self._time_provider.now() < self._calibration_cooldown_until:
            return False

        kp = yolo_result.keypoints.data[0]
        left_shoulder = kp[5]
        right_shoulder = kp[6]

        if len(left_shoulder) < 3 or len(right_shoulder) < 3:
            return False

        left_conf = float(left_shoulder[2])
        right_conf = float(right_shoulder[2])

        if (
            left_conf < self.SHOULDER_CONFIDENCE_THRESHOLD
            or right_conf < self.SHOULDER_CONFIDENCE_THRESHOLD
        ):
            self._rotation_consecutive = 0
            return False

        current_shoulder_width = abs(float(left_shoulder[0]) - float(right_shoulder[0]))

        width_ratio = current_shoulder_width / self.calibrated_shoulder_width
        width_change = abs(1.0 - width_ratio)

        if width_change > self.ROTATION_WIDTH_CHANGE_THRESHOLD:
            self._rotation_consecutive += 1
            if self._rotation_consecutive >= self.ROTATION_CONSECUTIVE_FRAMES:
                print(
                    f"[CAL] Body rotation detected (shoulder_width: {self.calibrated_shoulder_width:.0f}px → {current_shoulder_width:.0f}px), recalibrating..."
                )
                self._rotation_consecutive = 0
                return True
        else:
            self._rotation_consecutive = 0

        return False

    def trigger_recalibration(self):
        self.state = "recalibrating"
        self.calibration_samples = []
        self.calibration_start_time = self._time_provider.now()
        self.position_change_start = None
        self.last_stable_hip_centroid = None
        self._position_change_consecutive = 0
        self._neutral_settle_start = None
        self._no_person_start = None
        self._last_finalize_attempt_time = 0
        self._debug_frames_total = 0
        self._debug_frames_pose_ok = 0
        self._debug_add_sample_called = 0
        self._debug_samples_accepted = 0
        self._debug_reject_no_posture = 0
        self._debug_reject_no_neck_fwd = 0
        self._debug_reject_neck_range = 0
        self._debug_reject_back_range = 0
        self._debug_reject_fwd_lean_range = 0
        self._debug_last_log_time = 0

    def get_thresholds(self):
        if self.active_baseline is None:
            return None

        baseline = self.active_baseline

        # k=2.5 ≈ 2σ equivalent for MAD-based robust threshold
        neck_angle_threshold = baseline[
            "neck_angle_median"
        ] - self.MAD_MULTIPLIER * max(
            baseline["neck_angle_mad"], self.NECK_ANGLE_MAD_FLOOR
        )

        if baseline.get("has_back_angle", False):
            back_angle_threshold = baseline[
                "back_angle_median"
            ] - self.MAD_MULTIPLIER * max(
                baseline["back_angle_mad"], self.BACK_ANGLE_MAD_FLOOR
            )
        else:
            back_angle_threshold = None

        forward_lean_threshold = baseline[
            "forward_lean_median"
        ] + self.MAD_MULTIPLIER * max(
            baseline["forward_lean_mad"], self.FORWARD_LEAN_MAD_FLOOR
        )

        return {
            "neck_angle_threshold": neck_angle_threshold,
            "back_angle_threshold": back_angle_threshold,
            "forward_lean_threshold": forward_lean_threshold,
        }

    def match_baseline(self, pose_centroid):
        if not self.baselines or pose_centroid is None:
            return None

        distances = []
        for baseline in self.baselines:
            baseline_centroid = np.array(
                [baseline["pose_centroid_x"], baseline["pose_centroid_y"]]
            )
            centroid_dist = (
                np.linalg.norm(pose_centroid - baseline_centroid)
                / self.CENTROID_NORMALIZATION
            )
            distances.append(centroid_dist)

        min_idx = int(np.argmin(distances))
        min_distance = distances[min_idx]

        if min_distance < self.BASELINE_MATCH_THRESHOLD:
            return min_idx

        return None
