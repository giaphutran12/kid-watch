"""
KID-WATCH v0.3 — Engagement Engine
Combines posture + MoViNet studying confidence + phone detection
"""

import numpy as np
from datetime import datetime
from collections import deque

from .config import (
    STATE_HISTORY_SIZE,
    PHONE_DETECTION_FRAMES,
    SLOUCH_DETECTION_FRAMES,
    COLOR_STUDYING,
    COLOR_WARNING,
    COLOR_DISTRACTED,
)
from .utils import format_duration
from .time_provider import RealTime

# Threshold to convert continuous confidence to binary for hysteresis
STUDYING_CONFIDENCE_THRESHOLD = 0.5


class EngagementEngine:
    """Combines posture, MoViNet studying confidence, and phone detection."""

    # Hysteresis thresholds (seconds)
    SLOUCH_ENTER_DWELL = 0.85
    SLOUCH_EXIT_DWELL = 0.4
    STUDYING_ENTER_DWELL = 0.85
    STUDYING_EXIT_DWELL = 0.4

    # Engagement scoring weights
    WEIGHT_POSTURE = 0.20
    WEIGHT_STUDYING_CONFIDENCE = 0.55  # MoViNet — primary signal
    WEIGHT_NO_PHONE = 0.25

    # Phone detection confirmation ratio
    PHONE_CONFIRMATION_RATIO = 0.6

    # Focus score thresholds (%)
    FOCUS_EXCELLENT_THRESHOLD = 80
    FOCUS_GOOD_THRESHOLD = 60

    # Alert thresholds
    PHONE_ALERT_THRESHOLD = 5
    SLOUCH_ALERT_THRESHOLD = 10

    # Report formatting
    REPORT_SEPARATOR_WIDTH = 70

    def __init__(self, calibration_engine=None, time_provider=None):
        self.state_history = deque(maxlen=STATE_HISTORY_SIZE)
        self.phone_detection_buffer = deque(maxlen=PHONE_DETECTION_FRAMES)
        self.slouch_detection_buffer = deque(maxlen=SLOUCH_DETECTION_FRAMES)

        self.session_start = None
        self.session_active = False
        self.focus_scores = []
        self.phone_pickup_events = []
        self.slouch_events = []
        self.state_timeline = []

        self.current_state = "INITIALIZING"
        self.last_phone_detected = False
        self.last_slouch_detected = False

        self.slouch_signal_start_time = None
        self.slouch_exit_signal_start_time = None
        self.slouch_state_committed = False

        self.studying_signal_start_time = None
        self.studying_exit_signal_start_time = None
        self.studying_state_committed = False

        self.calibration_engine = calibration_engine
        self._time_provider = time_provider or RealTime()

    def _update_slouch_hysteresis(self, posture_good, current_time):
        """
        Update slouch state with hysteresis.
        Enter slouching: requires sustained bad posture for SLOUCH_ENTER_DWELL seconds
        Exit slouching: requires sustained good posture for SLOUCH_EXIT_DWELL seconds
        Returns: True if slouching confirmed, False otherwise
        """
        bad_posture = not posture_good

        if bad_posture:
            if self.slouch_signal_start_time is None:
                self.slouch_signal_start_time = current_time
            self.slouch_exit_signal_start_time = None

            elapsed = current_time - self.slouch_signal_start_time
            if elapsed >= self.SLOUCH_ENTER_DWELL:
                self.slouch_state_committed = True
        else:
            if self.slouch_exit_signal_start_time is None:
                self.slouch_exit_signal_start_time = current_time
            self.slouch_signal_start_time = None

            if self.slouch_state_committed:
                elapsed = current_time - self.slouch_exit_signal_start_time
                if elapsed >= self.SLOUCH_EXIT_DWELL:
                    self.slouch_state_committed = False

        return self.slouch_state_committed

    def _update_studying_hysteresis(self, studying, current_time):
        if studying:
            if self.studying_signal_start_time is None:
                self.studying_signal_start_time = current_time
            self.studying_exit_signal_start_time = None

            elapsed = current_time - self.studying_signal_start_time
            if elapsed >= self.STUDYING_ENTER_DWELL:
                self.studying_state_committed = True
        else:
            if self.studying_exit_signal_start_time is None:
                self.studying_exit_signal_start_time = current_time
            self.studying_signal_start_time = None

            if self.studying_state_committed:
                elapsed = current_time - self.studying_exit_signal_start_time
                if elapsed >= self.STUDYING_EXIT_DWELL:
                    self.studying_state_committed = False

        return self.studying_state_committed

    def start_session(self):
        """Start a new monitoring session."""
        self.session_start = datetime.now()
        self.session_active = True
        self.focus_scores = []
        self.phone_pickup_events = []
        self.slouch_events = []
        self.state_timeline = []
        self.current_state = "STUDYING"

        self.slouch_signal_start_time = None
        self.slouch_exit_signal_start_time = None
        self.slouch_state_committed = False
        self.studying_signal_start_time = None
        self.studying_exit_signal_start_time = None
        self.studying_state_committed = False

        print(
            f"\n[ENGAGEMENT] Session started at {self.session_start.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def stop_session(self):
        """Stop the current session."""
        self.session_active = False

    def reset_session(self):
        """Reset session data."""
        self.start_session()

    def update(
        self,
        posture_good,
        phone_detected,
        studying_confidence=0.5,
        person_present=True,
    ):
        if not self.session_active:
            return "SESSION PAUSED", 0, COLOR_WARNING

        if self.calibration_engine and self.calibration_engine.state in [
            "waiting",
            "calibrating",
            "recalibrating",
        ]:
            return (
                "WAITING"
                if self.calibration_engine.state == "waiting"
                else "CALIBRATING",
                0,
                COLOR_WARNING,
            )

        if not person_present:
            return "NO PERSON DETECTED", 0, COLOR_WARNING

        if posture_good is None:
            return "NO PERSON DETECTED", 0, COLOR_WARNING

        current_time = self._time_provider.now()

        studying_confidence = max(0.0, min(1.0, float(studying_confidence)))

        posture_score = 1.0 if posture_good else 0.0
        phone_score = 0.0 if phone_detected else 1.0

        frame_score = (
            self.WEIGHT_POSTURE * posture_score
            + self.WEIGHT_STUDYING_CONFIDENCE * studying_confidence
            + self.WEIGHT_NO_PHONE * phone_score
        )

        self.focus_scores.append(frame_score)

        self.phone_detection_buffer.append(phone_detected)
        phone_confirmed = (
            sum(self.phone_detection_buffer)
            >= PHONE_DETECTION_FRAMES * self.PHONE_CONFIRMATION_RATIO
        )

        if phone_confirmed and not self.last_phone_detected:
            self.phone_pickup_events.append(datetime.now())
        self.last_phone_detected = phone_confirmed

        slouch_confirmed = self._update_slouch_hysteresis(posture_good, current_time)

        studying_binary = studying_confidence >= STUDYING_CONFIDENCE_THRESHOLD
        studying_confirmed = self._update_studying_hysteresis(
            studying_binary, current_time
        )

        if slouch_confirmed and not self.last_slouch_detected:
            self.slouch_events.append(datetime.now())
        self.last_slouch_detected = slouch_confirmed

        if phone_confirmed:
            state = "DISTRACTED - PHONE"
            color = COLOR_DISTRACTED
        elif slouch_confirmed:
            state = "WARNING - SLOUCHING"
            color = COLOR_WARNING
        elif not studying_confirmed:
            state = "WARNING - NOT STUDYING"
            color = COLOR_WARNING
        else:
            state = "STUDYING"
            color = COLOR_STUDYING

        if state != self.current_state:
            self.state_timeline.append({"timestamp": datetime.now(), "state": state})
            self.current_state = state

        avg_focus = (
            np.mean(self.focus_scores) * 100 if len(self.focus_scores) > 0 else 0
        )

        return state, avg_focus, color

    def get_session_duration(self):
        """Get current session duration in seconds."""
        if self.session_start:
            return (datetime.now() - self.session_start).total_seconds()
        return 0

    def generate_report(self):
        """Generate detailed session report."""
        if not self.session_start:
            return "No session data available."

        duration = self.get_session_duration()
        avg_focus = np.mean(self.focus_scores) * 100 if self.focus_scores else 0

        report = []
        report.append("\n" + "=" * self.REPORT_SEPARATOR_WIDTH)
        report.append("KID-WATCH SESSION REPORT")
        report.append("=" * self.REPORT_SEPARATOR_WIDTH)
        report.append(
            f"Session Start:     {self.session_start.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        report.append(
            f"Session End:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        report.append(f"Total Duration:    {format_duration(duration)}")
        report.append("-" * self.REPORT_SEPARATOR_WIDTH)
        report.append(f"Focus Score:       {avg_focus:.1f}%")
        report.append(f"Phone Pickups:     {len(self.phone_pickup_events)}")
        report.append(f"Posture Alerts:    {len(self.slouch_events)}")
        report.append("-" * self.REPORT_SEPARATOR_WIDTH)

        report.append("STATE TIMELINE:")
        if self.state_timeline:
            for i, event in enumerate(self.state_timeline[:10]):
                timestamp = event["timestamp"].strftime("%H:%M:%S")
                report.append(f"  [{timestamp}] → {event['state']}")
            if len(self.state_timeline) > 10:
                report.append(
                    f"  ... and {len(self.state_timeline) - 10} more state changes"
                )
        else:
            report.append("  No state changes recorded")

        report.append("-" * self.REPORT_SEPARATOR_WIDTH)

        report.append("RECOMMENDATIONS:")
        if avg_focus >= self.FOCUS_EXCELLENT_THRESHOLD:
            report.append("  ✓ Excellent focus! Keep up the great work.")
        elif avg_focus >= self.FOCUS_GOOD_THRESHOLD:
            report.append("  • Good session. Try to minimize phone distractions.")
        else:
            report.append("  ⚠ Focus needs improvement. Consider:")

        if len(self.phone_pickup_events) > self.PHONE_ALERT_THRESHOLD:
            report.append("  • Put phone in another room or use app blockers")
        if len(self.slouch_events) > self.SLOUCH_ALERT_THRESHOLD:
            report.append(
                "  • Adjust chair height and monitor position for better posture"
            )

        report.append("=" * self.REPORT_SEPARATOR_WIDTH + "\n")

        return "\n".join(report)
