#!/usr/bin/env python3
"""
KID-WATCH v0.3 — Real-time Study Session Monitor
Production PoC for Viettel deployment (700k home cameras)

Monitors: posture, phone usage, action recognition, engagement scoring
Technologies: YOLOv8n-pose, MoViNet-A2-Stream, OpenCV
"""

import cv2
import numpy as np
from collections import deque
import time
import sys
import os
import atexit
import argparse
from datetime import datetime

from kid_watch.config import (
    CAMERA_INDEX,
    FRAME_WIDTH,
    FRAME_HEIGHT,
    TARGET_FPS,
    USE_ML_DETECTOR,
    MOVINET_SKIP_FRAMES,
)
from kid_watch.detectors import PhoneDetector
from kid_watch.calibration import CalibrationEngine
from kid_watch.engagement import EngagementEngine
from kid_watch.dashboard import DashboardRenderer
from kid_watch.time_provider import RealTime, VideoTime

if USE_ML_DETECTOR:
    from kid_watch.detectors import (
        YoloPoseDetector,
        MoViNetDetector,
        DetectionStateMachine,
        GazeDetector,
    )
else:
    from kid_watch.detectors import (
        PostureDetector,
        GazeDetector,
        StudyDetector,
    )


# ============================================================================
# TERMINAL LOGGING
# ============================================================================


class _TeeStream:
    """Writes to both terminal and a log file simultaneously."""

    def __init__(self, terminal, log_file):
        self.terminal = terminal
        self.log_file = log_file

    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)
        self.log_file.flush()  # Ensure real-time writing

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def isatty(self):
        return self.terminal.isatty()


_log_file = None


def _setup_terminal_logging():
    """Auto-save all terminal output to data/terminal-debug/."""
    global _log_file

    log_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "terminal-debug"
    )
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%b%d_%I%M%p").lower()
    log_path = os.path.join(log_dir, f"{timestamp}.txt")

    _log_file = open(log_path, "w")
    sys.stdout = _TeeStream(sys.__stdout__, _log_file)
    sys.stderr = _TeeStream(sys.__stderr__, _log_file)

    return log_path


def _cleanup_terminal_logging():
    """Close the log file on exit."""
    global _log_file
    if _log_file:
        _log_file.close()


atexit.register(_cleanup_terminal_logging)


# ============================================================================
# MAIN APPLICATION
# ============================================================================


class KidWatchApp:
    """Main application orchestrator."""

    def __init__(self, args=None):
        self.args = (
            args
            if args
            else argparse.Namespace(
                video=None,
                record=False,
                save_annotated=None,
                no_display=False,
                eval=None,
            )
        )

        print("\n" + "=" * 70)
        print(f"KID-WATCH v0.{'3' if USE_ML_DETECTOR else '1'} — Study Session Monitor")
        print("Production PoC for Viettel (700k home camera deployment)")
        print("=" * 70 + "\n")

        # Initialize evaluation system if --eval is provided
        self.evaluator = None
        self.scenario = None
        if self.args.eval:
            from kid_watch.eval.scenario import load_scenario
            from kid_watch.eval.evaluator import Evaluator

            print(f"[EVAL] Loading scenario: {self.args.eval}")
            try:
                self.scenario = load_scenario(self.args.eval)
                self.evaluator = Evaluator()
                print(f"[EVAL] Scenario loaded: {len(self.scenario.segments)} segments")
                print(f"[EVAL] Video: {self.scenario.video_path}")
            except Exception as e:
                print(f"[EVAL] ERROR: Failed to load scenario: {e}")
                sys.exit(1)

        # Initialize video capture first to determine TimeProvider type
        if self.args.video:
            print(f"Opening video file: {self.args.video}")
            self.cap = cv2.VideoCapture(self.args.video)
            if not self.cap.isOpened():
                raise RuntimeError(
                    f"ERROR: Could not open video file: {self.args.video}"
                )

            # Get video properties
            self.video_fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration_sec = total_frames / self.video_fps if self.video_fps > 0 else 0
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            print(f"Video properties:")
            print(f"  Resolution: {actual_width}x{actual_height}")
            print(f"  FPS: {self.video_fps:.2f}")
            print(f"  Total frames: {total_frames}")
            print(f"  Duration: {duration_sec:.1f}s ({duration_sec / 60:.1f} min)")

            # Create VideoTime provider
            self.clock = VideoTime(self.video_fps)
            self.video_mode = True
        else:
            print(f"Opening camera {CAMERA_INDEX}...")
            self.cap = cv2.VideoCapture(CAMERA_INDEX)
            if not self.cap.isOpened():
                raise RuntimeError(
                    "ERROR: Could not open webcam. Please check camera connection."
                )

            # Set camera properties
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            self.cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)

            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"Camera resolution: {actual_width}x{actual_height}")

            # Create RealTime provider
            self.clock = RealTime()
            self.video_mode = False
            self.video_fps = TARGET_FPS

        print("Initializing components...")
        self.calibration_engine = CalibrationEngine(time_provider=self.clock)
        self.phone_detector = PhoneDetector()
        self.engagement_engine = EngagementEngine(
            self.calibration_engine, time_provider=self.clock
        )

        if USE_ML_DETECTOR:
            self.posture_detector = YoloPoseDetector(
                self.calibration_engine, time_provider=self.clock
            )
            self.movinet_detector = MoViNetDetector(time_provider=self.clock)
            self.gaze_detector = GazeDetector(self.calibration_engine)
            self.state_machine = DetectionStateMachine()
            self._frame_count = 0
            self._last_action = "other"
            self._last_action_confidence = 0.0
            self._no_person_frames = 0
            self._last_posture_good = True
            self._last_gaze_log_time = 0
        else:
            self.posture_detector = PostureDetector(self.calibration_engine)
            self.gaze_detector = GazeDetector(self.calibration_engine)
            self.study_detector = StudyDetector(
                self.calibration_engine, time_provider=self.clock
            )

        self._debug_csv_file = None
        self._debug_csv_writer = None
        self._debug_csv_active = False

        self.dashboard = DashboardRenderer(actual_width, actual_height)

        self.fps_history = deque(maxlen=30)
        self.last_frame_time = self.clock.now()

        # Initialize video recording writers
        self.raw_writer = None
        self.annotated_writer = None

        if self.args.record:
            rec_dir = "data/recordings"
            os.makedirs(rec_dir, exist_ok=True)
            timestamp_str = datetime.now().strftime("%b%d_%I%M%p").lower()
            raw_path = os.path.join(rec_dir, f"raw_{timestamp_str}.mp4")
            fourcc = cv2.VideoWriter.fourcc(*"mp4v")
            self.raw_writer = cv2.VideoWriter(
                raw_path, fourcc, self.video_fps, (actual_width, actual_height)
            )
            print(f"[RECORD] Saving raw frames to: {raw_path}")

        if self.args.save_annotated:
            fourcc = cv2.VideoWriter.fourcc(*"mp4v")
            self.annotated_writer = cv2.VideoWriter(
                self.args.save_annotated,
                fourcc,
                self.video_fps,
                (actual_width, actual_height),
            )
            print(f"[RECORD] Saving annotated frames to: {self.args.save_annotated}")

        print("\n✓ Initialization complete!")
        print("\nStarting session automatically...")
        self.engagement_engine.start_session()
        self.calibration_engine.start_calibration()

        # Auto-start CSV logging
        self._start_csv_logging()

    def _start_csv_logging(self):
        """Initialize and start CSV debug logging."""
        import csv

        csv_dir = "data/debug-csv"
        os.makedirs(csv_dir, exist_ok=True)

        timestamp_str = datetime.now().strftime("%b%d_%I%M%p").lower()
        filename = os.path.join(csv_dir, f"{timestamp_str}.csv")

        self._debug_csv_file = open(filename, "w", newline="")
        self._debug_csv_writer = csv.writer(self._debug_csv_file)
        self._debug_csv_writer.writerow(
            [
                "timestamp",
                "frame",
                "state",
                "source",
                "studying",
                "person_present",
                "neck_flex",
                "forward_lean",
                "pitch",
                "yaw",
                "gaze_at_desk",
                "posture_good",
                "phone_detected",
                "focus_score",
                "camera_mode",
                "neck_angle",
                "back_angle",
                "forward_lean_smoothed",
            ]
        )
        self._debug_csv_active = True
        print(f"[DEBUG] CSV logging started → {filename}")

    def run(self):
        """Main application loop."""
        if not self.video_mode:
            print("\nPress 'Q' to quit and see session report\n")
        else:
            print("\nProcessing video... Press 'Q' to stop early\n")

        frame_num = 0
        total_frames = (
            int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) if self.video_mode else 0
        )

        try:
            while True:
                if self.video_mode:
                    self.clock.tick(self.cap)

                ret, frame = self.cap.read()
                if not ret:
                    if self.video_mode:
                        print(f"\n✓ Video processing complete ({frame_num} frames)")
                    else:
                        print("ERROR: Failed to read frame from camera")
                    break

                frame_num += 1

                if self.video_mode and frame_num % 100 == 0:
                    progress_pct = (
                        (frame_num / total_frames * 100) if total_frames > 0 else 0
                    )
                    print(
                        f"[VIDEO-TEST] Frame {frame_num}/{total_frames} ({progress_pct:.1f}%)"
                    )

                if self.raw_writer:
                    self.raw_writer.write(frame)

                if not self.video_mode:
                    frame = cv2.flip(frame, 1)

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                if USE_ML_DETECTOR:
                    phone_detected, phone_boxes = self.phone_detector.detect(frame)

                    posture_good, posture_metrics, yolo_result = (
                        self.posture_detector.detect(frame_rgb)
                    )

                    # Run gaze detection
                    gaze_at_desk, pitch, yaw, iris_ratio, face_width = (
                        self.gaze_detector.detect(frame_rgb)
                    )

                    self._frame_count += 1
                    if self._frame_count % MOVINET_SKIP_FRAMES == 0:
                        action_label, action_confidence, _ = (
                            self.movinet_detector.detect(frame_rgb)
                        )
                        self._last_action = action_label
                        self._last_action_confidence = action_confidence

                    person_present = (
                        yolo_result is not None
                        and hasattr(yolo_result, "keypoints")
                        and yolo_result.keypoints is not None
                        and len(yolo_result.keypoints.data) > 0
                    )
                    # Hold last known posture when detection fails (don't assume good)
                    if posture_good is not None:
                        self._last_posture_good = posture_good
                    state_machine_state, state_confidence = self.state_machine.update(
                        action_prediction=self._last_action,
                        phone_detected=phone_detected,
                        posture_good=self._last_posture_good,
                        person_present=person_present,
                    )

                    studying_confidence = (
                        self._last_action_confidence
                        if self._last_action == "studying"
                        else 0.0
                    )

                    # GAZE GATE: Override studying_confidence if looking away
                    if gaze_at_desk is False:
                        studying_confidence = 0.0
                    # REVERSE GAZE GATE: If looking at desk but MoViNet disagrees, trust gaze partially
                    elif gaze_at_desk is True and studying_confidence == 0.0:
                        studying_confidence = 0.5
                        current_time = self.clock.now()
                        if current_time - self._last_gaze_log_time >= 1.0:
                            print(
                                f"[GAZE] Reverse gate: gaze_at_desk=True overrides MoViNet (action={self._last_action}) → studying_confidence=0.5"
                            )
                            self._last_gaze_log_time = current_time

                    if not person_present:
                        self._no_person_frames += 1
                        if self._no_person_frames > 150:
                            self.movinet_detector.reset_state()
                            self._no_person_frames = 0
                    else:
                        self._no_person_frames = 0

                    pose_result = yolo_result

                else:
                    gaze_at_desk, pitch, yaw, iris_ratio, face_width = (
                        self.gaze_detector.detect(frame_rgb)
                    )
                    posture_good, posture_metrics, pose_result = (
                        self.posture_detector.detect(frame_rgb, face_width)
                    )
                    phone_detected, phone_boxes = self.phone_detector.detect(frame)

                    person_present, studying, study_source = self.study_detector.detect(
                        gaze_at_desk, pose_result, posture_metrics
                    )
                    studying_confidence = 0.5

                if USE_ML_DETECTOR:
                    current_time = self.clock.now()
                    if not hasattr(self, "_last_study_log_time"):
                        self._last_study_log_time = 0
                    if not hasattr(self, "_last_gaze_log_time"):
                        self._last_gaze_log_time = 0
                    if current_time - self._last_study_log_time >= 1.0:
                        print(
                            f"[ML] action={self._last_action} conf={self._last_action_confidence:.2f} "
                            f"state={state_machine_state.value} person={person_present}"
                        )
                        self._last_study_log_time = current_time
                    if current_time - self._last_gaze_log_time >= 1.0:
                        if pitch is not None and yaw is not None:
                            print(
                                f"[GAZE] at_desk={gaze_at_desk} pitch={pitch:.1f} yaw={yaw:.1f}"
                            )
                        self._last_gaze_log_time = current_time
                else:
                    if study_source != "none":
                        current_time = self.clock.now()
                        if not hasattr(self, "_last_study_log_time"):
                            self._last_study_log_time = 0
                        if current_time - self._last_study_log_time >= 1.0:
                            if study_source in ("pose_side", "pose", "pose_fallback"):
                                neck_flex = (
                                    self.study_detector._compute_neck_flexion(
                                        pose_result
                                    )
                                    if pose_result and pose_result.pose_landmarks
                                    else None
                                )
                                if neck_flex is not None:
                                    print(
                                        f"[STUDY] source={study_source} neck_flex={neck_flex:.1f}° studying={studying}"
                                    )
                            elif study_source in ("face", "face_fallback"):
                                print(
                                    f"[STUDY] source={study_source} pitch={pitch:.1f}° yaw={yaw:.1f}° gaze_at_desk={gaze_at_desk} studying={studying}"
                                )
                            elif study_source == "side_face_override":
                                print(
                                    f"[STUDY] source=side_face_override → NOT studying (face visible from side cam)"
                                )
                            elif study_source == "face_hold":
                                print(
                                    f"[STUDY] source=face_hold studying={studying} (holding last gaze decision)"
                                )
                            self._last_study_log_time = current_time

                calibration_progress = None
                if self.calibration_engine.state == "waiting":
                    state_changed, msg = self.calibration_engine.update_waiting_state(
                        posture_metrics
                    )
                    calibration_progress = -1

                elif self.calibration_engine.state in ["calibrating", "recalibrating"]:
                    self.calibration_engine._debug_frames_total += 1

                    if USE_ML_DETECTOR:
                        if (
                            yolo_result is not None
                            and hasattr(yolo_result, "keypoints")
                            and len(yolo_result.keypoints.data) > 0
                        ):
                            self.calibration_engine._debug_frames_pose_ok += 1
                            kp = yolo_result.keypoints.data[0]
                            left_shoulder = kp[5]
                            right_shoulder = kp[6]
                            pose_centroid = np.array(
                                [
                                    (left_shoulder[0] + right_shoulder[0]) / 2,
                                    (left_shoulder[1] + right_shoulder[1]) / 2,
                                ]
                            )

                            shoulder_width = None
                            if len(left_shoulder) >= 3 and len(right_shoulder) >= 3:
                                left_conf = float(left_shoulder[2])
                                right_conf = float(right_shoulder[2])
                                if left_conf > 0.3 and right_conf > 0.3:
                                    shoulder_width = abs(
                                        float(left_shoulder[0])
                                        - float(right_shoulder[0])
                                    )

                            self.calibration_engine.add_sample(
                                posture_metrics,
                                pose_centroid,
                                shoulder_width=shoulder_width,
                            )
                        else:
                            self.calibration_engine.mark_person_absent()
                    else:
                        if pose_result and pose_result.pose_landmarks:
                            self.calibration_engine._debug_frames_pose_ok += 1
                            landmarks = pose_result.pose_landmarks[0]
                            left_shoulder = landmarks[11]
                            right_shoulder = landmarks[12]
                            pose_centroid = np.array(
                                [
                                    (left_shoulder.x + right_shoulder.x) / 2,
                                    (left_shoulder.y + right_shoulder.y) / 2,
                                ]
                            )
                            self.calibration_engine.add_sample(
                                posture_metrics, pose_centroid
                            )

                    progress, should_finalize = (
                        self.calibration_engine.check_calibration_progress()
                    )
                    calibration_progress = progress

                    self.calibration_engine._debug_log_calibration_stats()

                    if should_finalize:
                        success = self.calibration_engine.finalize_calibration()
                        if success:
                            print("\n✓ Calibration complete!")
                        else:
                            now = self.clock.now()
                            if (
                                now - self.calibration_engine._last_extended_log_time
                                >= self.calibration_engine.EXTENDED_LOG_INTERVAL
                            ):
                                print("\n⚠ Calibration extended (insufficient data)")
                                self.calibration_engine._last_extended_log_time = now

                elif self.calibration_engine.state == "active":
                    if USE_ML_DETECTOR:
                        if (
                            yolo_result is not None
                            and hasattr(yolo_result, "keypoints")
                            and len(yolo_result.keypoints.data) > 0
                        ):
                            kp = yolo_result.keypoints.data[0]
                            left_shoulder = kp[5][:2]
                            right_shoulder = kp[6][:2]
                            pose_centroid = np.array(
                                [
                                    (left_shoulder[0] + right_shoulder[0]) / 2,
                                    (left_shoulder[1] + right_shoulder[1]) / 2,
                                ]
                            )

                            # Compute hip centroid for stable position tracking
                            hip_centroid = None
                            left_hip_conf = float(kp[11][2]) if len(kp[11]) > 2 else 0.0
                            right_hip_conf = (
                                float(kp[12][2]) if len(kp[12]) > 2 else 0.0
                            )
                            if left_hip_conf > 0.3 and right_hip_conf > 0.3:
                                left_hip = kp[11][:2]
                                right_hip = kp[12][:2]
                                hip_centroid = np.array(
                                    [
                                        (left_hip[0] + right_hip[0]) / 2,
                                        (left_hip[1] + right_hip[1]) / 2,
                                    ]
                                )

                            # Get forward_lean from posture metrics (computed earlier in the frame)
                            current_forward_lean = None
                            if posture_metrics is not None:
                                current_forward_lean = posture_metrics.get(
                                    "forward_lean_angle"
                                )

                            position_changed = (
                                self.calibration_engine.check_position_change(
                                    pose_centroid,
                                    hip_centroid=hip_centroid,
                                    forward_lean=current_forward_lean,
                                )
                            )
                            rotation_detected = (
                                self.calibration_engine.check_body_rotation(yolo_result)
                            )

                            if position_changed:
                                print("\n⚠ Position change detected, recalibrating...")
                                self.calibration_engine.trigger_recalibration()
                            elif rotation_detected:
                                self.calibration_engine.trigger_recalibration()
                    else:
                        if pose_result and pose_result.pose_landmarks and face_width:
                            landmarks = pose_result.pose_landmarks[0]
                            left_shoulder = landmarks[11]
                            right_shoulder = landmarks[12]
                            pose_centroid = np.array(
                                [
                                    (left_shoulder.x + right_shoulder.x) / 2,
                                    (left_shoulder.y + right_shoulder.y) / 2,
                                ]
                            )
                            if self.calibration_engine.check_position_change(
                                face_width, pose_centroid
                            ):
                                print("\n⚠ Position change detected, recalibrating...")
                                self.calibration_engine.trigger_recalibration()

                if USE_ML_DETECTOR:
                    state, focus_score, status_color = self.engagement_engine.update(
                        self._last_posture_good,
                        phone_detected,
                        studying_confidence=studying_confidence,
                        person_present=person_present,
                    )
                else:
                    state, focus_score, status_color = self.engagement_engine.update(
                        posture_good,
                        phone_detected,
                        studying_confidence,
                        person_present,
                    )

                if self.evaluator and self.scenario:
                    current_time = self.clock.now()
                    expected_state = self.scenario.get_expected_state(current_time)

                    if USE_ML_DETECTOR:
                        state_value = state_machine_state.value.upper()
                        if state_value == "AWAY":
                            actual_state = "ABSENT"
                        else:
                            actual_state = state_value
                    else:
                        if not person_present:
                            actual_state = "ABSENT"
                        elif phone_detected:
                            actual_state = "PHONE"
                        elif not posture_good:
                            actual_state = "SLOUCHING"
                        elif studying:
                            actual_state = "STUDYING"
                        else:
                            actual_state = "DISTRACTED"

                    self.evaluator.record(
                        time_seconds=current_time,
                        expected_state=expected_state,
                        actual_state=actual_state,
                        details={"focus_score": focus_score},
                    )

                if (
                    self._debug_csv_active
                    and self._debug_csv_file
                    and self._debug_csv_writer
                ):
                    if USE_ML_DETECTOR:
                        forward_lean_val = (
                            posture_metrics.get("forward_lean_angle")
                            if posture_metrics
                            else None
                        )
                        neck_angle_val = (
                            posture_metrics.get("neck_angle")
                            if posture_metrics
                            else None
                        )
                        back_angle_val = (
                            posture_metrics.get("back_angle")
                            if posture_metrics
                            else None
                        )
                        forward_lean_smoothed_val = (
                            posture_metrics.get("forward_lean_smoothed")
                            if posture_metrics
                            else None
                        )
                        self._debug_csv_writer.writerow(
                            [
                                f"{self.clock.now():.3f}",
                                self._frame_count,
                                state,
                                self._last_action,
                                self._last_action_confidence,
                                person_present,
                                "",
                                f"{forward_lean_val:.1f}"
                                if forward_lean_val is not None
                                else "",
                                f"{pitch:.1f}" if pitch is not None else "",
                                f"{yaw:.1f}" if yaw is not None else "",
                                gaze_at_desk if gaze_at_desk is not None else "",
                                posture_good,
                                phone_detected,
                                f"{focus_score:.1f}",
                                "ml_detector",
                                f"{neck_angle_val:.1f}"
                                if neck_angle_val is not None
                                else "",
                                f"{back_angle_val:.1f}"
                                if back_angle_val is not None
                                else "",
                                f"{forward_lean_smoothed_val:.1f}"
                                if forward_lean_smoothed_val is not None
                                else "",
                            ]
                        )
                    else:
                        neck_flex_val = (
                            self.study_detector._compute_neck_flexion(pose_result)
                            if pose_result and pose_result.pose_landmarks
                            else None
                        )
                        forward_lean_val = (
                            posture_metrics.get("forward_lean_angle")
                            if posture_metrics
                            else None
                        )
                        neck_angle_val = (
                            posture_metrics.get("neck_angle")
                            if posture_metrics
                            else None
                        )
                        back_angle_val = (
                            posture_metrics.get("back_angle")
                            if posture_metrics
                            else None
                        )
                        forward_lean_smoothed_val = (
                            posture_metrics.get("forward_lean_smoothed")
                            if posture_metrics
                            else None
                        )
                        self._debug_csv_writer.writerow(
                            [
                                f"{self.clock.now():.3f}",
                                self.study_detector._frame_count
                                if hasattr(self.study_detector, "_frame_count")
                                else "",
                                state,
                                study_source,
                                studying,
                                person_present,
                                f"{neck_flex_val:.1f}"
                                if neck_flex_val is not None
                                else "",
                                f"{forward_lean_val:.1f}"
                                if forward_lean_val is not None
                                else "",
                                f"{pitch:.1f}" if pitch is not None else "",
                                f"{yaw:.1f}" if yaw is not None else "",
                                gaze_at_desk,
                                posture_good,
                                phone_detected,
                                f"{focus_score:.1f}",
                                self.study_detector._camera_mode or "unknown",
                                f"{neck_angle_val:.1f}"
                                if neck_angle_val is not None
                                else "",
                                f"{back_angle_val:.1f}"
                                if back_angle_val is not None
                                else "",
                                f"{forward_lean_smoothed_val:.1f}"
                                if forward_lean_smoothed_val is not None
                                else "",
                            ]
                        )
                    self._debug_csv_file.flush()

                if USE_ML_DETECTOR:
                    if yolo_result is not None and hasattr(yolo_result, "plot"):
                        frame = yolo_result.plot(img=frame, kpt_radius=3, kpt_line=True)
                else:
                    self.posture_detector.draw_skeleton(frame, pose_result)

                if USE_ML_DETECTOR:
                    self.dashboard.render(
                        frame,
                        state,
                        focus_score,
                        self.engagement_engine.get_session_duration(),
                        len(self.engagement_engine.phone_pickup_events),
                        len(self.engagement_engine.slouch_events),
                        phone_boxes,
                        None,
                        posture_metrics,
                        calibration_progress,
                        action_label=self._last_action,
                        action_confidence=self._last_action_confidence,
                        person_present=person_present,
                    )
                else:
                    self.dashboard.render(
                        frame,
                        state,
                        focus_score,
                        self.engagement_engine.get_session_duration(),
                        len(self.engagement_engine.phone_pickup_events),
                        len(self.engagement_engine.slouch_events),
                        phone_boxes,
                        iris_ratio,
                        posture_metrics,
                        calibration_progress,
                        person_present=person_present,
                    )

                current_time = self.clock.now()
                fps = 1.0 / (current_time - self.last_frame_time + 1e-6)
                self.fps_history.append(fps)
                avg_fps = np.mean(self.fps_history)
                self.last_frame_time = current_time

                cv2.putText(
                    frame,
                    f"FPS: {avg_fps:.1f}",
                    (20, self.dashboard.height - 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (180, 180, 180),
                    1,
                    cv2.LINE_AA,
                )

                if self.annotated_writer:
                    self.annotated_writer.write(frame)

                if not self.args.no_display:
                    cv2.imshow("KID-WATCH - Study Monitor", frame)
                    key = cv2.waitKey(1) & 0xFF
                else:
                    key = 0xFF

                if key == ord("q") or key == ord("Q"):
                    print("\nQuitting...")
                    break
                elif key == ord("s") or key == ord("S"):
                    if self.engagement_engine.session_active:
                        self.engagement_engine.stop_session()
                        print("\n[SESSION PAUSED]")
                    else:
                        self.engagement_engine.start_session()
                elif key == ord("r") or key == ord("R"):
                    self.engagement_engine.reset_session()
                    print("\n[SESSION RESET]")
                elif key == ord("d") or key == ord("D"):
                    if self._debug_csv_active:
                        if self._debug_csv_file:
                            self._debug_csv_file.close()
                            self._debug_csv_file = None
                        self._debug_csv_active = False
                        print("\n[DEBUG] CSV logging stopped")
                    else:
                        self._start_csv_logging()

        except KeyboardInterrupt:
            print("\n\nInterrupted by user")

        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources and show report."""
        if self._debug_csv_file:
            self._debug_csv_file.close()

        if self.raw_writer:
            self.raw_writer.release()
            print("[RECORD] Raw recording saved")

        if self.annotated_writer:
            self.annotated_writer.release()
            print("[RECORD] Annotated recording saved")

        if self.evaluator and self.scenario:
            from kid_watch.eval.reporter import (
                generate_report,
                print_report,
                save_report,
            )

            print("\n[EVAL] Computing evaluation statistics...")
            stats = self.evaluator.compute_stats()
            failures = self.evaluator.get_failures()
            delays = self.evaluator.get_transition_delays()

            video_path = self.args.video if self.args.video else "live_camera"
            eval_report = generate_report(
                stats, failures, delays, self.args.eval, video_path
            )

            print("\n" + "=" * 70)
            print("EVALUATION REPORT")
            print("=" * 70)
            print_report(eval_report)

            os.makedirs("data/eval-reports", exist_ok=True)
            timestamp_str = datetime.now().strftime("%b%d_%I%M%p").lower()
            report_path = f"data/eval-reports/{timestamp_str}_report.txt"
            save_report(eval_report, report_path)
            print(f"\n[EVAL] Report saved to: {report_path}")

        print("\nGenerating session report...")
        report = self.engagement_engine.generate_report()
        print(report)

        self.cap.release()
        cv2.destroyAllWindows()
        print("Resources released. Goodbye!\n")


# ============================================================================
# ENTRY POINT
# ============================================================================


def main():
    """Application entry point."""
    parser = argparse.ArgumentParser(description="KID-WATCH Study Monitor")
    parser.add_argument(
        "--video", type=str, help="Path to video file (replaces live camera)"
    )
    parser.add_argument(
        "--record", action="store_true", help="Record raw camera frames to MP4"
    )
    parser.add_argument(
        "--save-annotated", type=str, help="Save annotated frames to MP4"
    )
    parser.add_argument(
        "--no-display", action="store_true", help="Skip display (headless mode)"
    )
    parser.add_argument("--eval", type=str, help="Path to scenario YAML for evaluation")
    args = parser.parse_args()

    log_path = _setup_terminal_logging()
    print(f"[LOG] Terminal output auto-saved to: {log_path}\n")

    try:
        app = KidWatchApp(args=args)
        app.run()
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
