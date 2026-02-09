"""
KID-WATCH v0.1 — Dashboard Renderer
Renders professional UI overlay on video frame
"""

import cv2

from .config import (
    COLOR_STUDYING,
    COLOR_WARNING,
    COLOR_DISTRACTED,
    COLOR_TEXT,
    COLOR_OVERLAY_BG,
    COLOR_PHONE_BOX,
)
from .utils import draw_text_with_background, format_duration

# ============================================================
# Dashboard Constants
# ============================================================

# --- Calibration Panel ---
CALIBRATION_PANEL_WIDTH = 400
CALIBRATION_PANEL_HEIGHT = 100
CALIBRATION_PANEL_Y = 100
CALIBRATION_PANEL_PADDING = 20
CALIBRATION_PANEL_BORDER_THICKNESS = 3
CALIBRATION_TEXT_Y_OFFSET = 35
CALIBRATION_SUBTEXT_Y_OFFSET = 60
CALIBRATION_BAR_Y_OFFSET = 75
CALIBRATION_BAR_HEIGHT = 15
CALIBRATION_BAR_MARGIN = 40
CALIBRATION_PROGRESS_TEXT_X_OFFSET = 10
CALIBRATION_PROGRESS_TEXT_Y_OFFSET = 12

# --- Top Bar ---
TOP_BAR_HEIGHT = 60
TOP_BAR_TITLE_X = 20
TOP_BAR_TITLE_Y = 35
TOP_BAR_SUBTITLE_Y = 52
TOP_BAR_SESSION_X_OFFSET = 250
TOP_BAR_SESSION_Y = 40

# --- Status Panel ---
STATUS_PANEL_WIDTH = 320
STATUS_PANEL_MARGIN = 20
STATUS_PANEL_Y = 80
STATUS_PANEL_HEIGHT = 280
STATUS_PANEL_BORDER_THICKNESS = 3
STATUS_PANEL_PADDING = 20
STATUS_HEADER_Y_OFFSET = 40
STATUS_STATE_LINE_SPACING = 30
STATUS_STATE_HEADER_SPACING = 35
STATUS_SECTION_SPACING = 10
STATUS_LABEL_SPACING = 30
STATUS_ALERT_LINE_SPACING = 25
FOCUS_BAR_WIDTH = 260
FOCUS_BAR_HEIGHT = 25
FOCUS_BAR_Y_ADJUST = 20
FOCUS_SCORE_X_OFFSET = 10
FOCUS_SCORE_Y_ADJUST = 5
FOCUS_SCORE_HIGH_THRESHOLD = 80
FOCUS_SCORE_MEDIUM_THRESHOLD = 60
STATUS_SCORE_SPACING = 40

# --- Debug Panel ---
DEBUG_PANEL_X = 20
DEBUG_PANEL_Y = 100
DEBUG_PANEL_WIDTH = 220
DEBUG_PANEL_BASE_HEIGHT = 30
DEBUG_LINE_SPACING = 25
DEBUG_TEXT_PADDING = 10
DEBUG_HEADER_Y_OFFSET = 25
DEBUG_CONTENT_Y_OFFSET = 50
DEBUG_ACTION_CONFIDENCE_THRESHOLD = 0.5
DEBUG_IRIS_RATIO_THRESHOLD = 0.52
DEBUG_NECK_ANGLE_GOOD = 150
DEBUG_NECK_ANGLE_WARNING = 140
DEBUG_BACK_ANGLE_GOOD = 160
DEBUG_BACK_ANGLE_WARNING = 150
DEBUG_FORWARD_HEAD_RATIO_THRESHOLD = 1.10

# --- Phone Box ---
PHONE_BOX_THICKNESS = 3
PHONE_LABEL_BG_PADDING = 10
PHONE_LABEL_TEXT_MARGIN = 5

# --- Controls Hint ---
CONTROLS_HINT_BOTTOM_MARGIN = 15

# --- Font Scales ---
FONT_SCALE_TITLE = 1.0
FONT_SCALE_LARGE = 0.8
FONT_SCALE_MEDIUM = 0.7
FONT_SCALE_LABEL = 0.6
FONT_SCALE_SMALL = 0.5

# --- Font Thickness ---
FONT_THICKNESS_BOLD = 2
FONT_THICKNESS_NORMAL = 1

# --- Overlay Alpha Values ---
CALIBRATION_OVERLAY_ALPHA = 0.9
TOP_BAR_OVERLAY_ALPHA = 0.8
STATUS_PANEL_OVERLAY_ALPHA = 0.85
DEBUG_PANEL_OVERLAY_ALPHA = 0.85

# --- Colors (BGR format) ---
COLOR_GRAY_LIGHT = (200, 200, 200)
COLOR_GRAY_MEDIUM = (180, 180, 180)
COLOR_GRAY_DARK = (60, 60, 60)

# --- Percentage Multiplier ---
PERCENT_MULTIPLIER = 100


class DashboardRenderer:
    """Renders professional UI overlay on video frame."""

    def __init__(self, frame_width, frame_height):
        self.width = frame_width
        self.height = frame_height

    def render(
        self,
        frame,
        state,
        focus_score,
        session_duration,
        phone_count,
        slouch_count,
        phone_boxes=None,
        iris_ratio=None,
        posture_metrics=None,
        calibration_progress=None,
        action_label=None,
        action_confidence=None,
        person_present=True,
    ):
        self._draw_top_bar(frame, session_duration)

        if calibration_progress is not None:
            self._draw_calibration_status(frame, calibration_progress, person_present)

        self._draw_status_panel(frame, state, focus_score, phone_count, slouch_count)

        if (
            iris_ratio is not None
            or posture_metrics is not None
            or action_label is not None
        ):
            self._draw_debug_info(
                frame, iris_ratio, posture_metrics, action_label, action_confidence
            )

        if phone_boxes:
            for phone in phone_boxes:
                self._draw_phone_box(frame, phone)

        self._draw_controls_hint(frame)

    def _draw_calibration_status(self, frame, progress, person_present=True):
        panel_width = CALIBRATION_PANEL_WIDTH
        panel_height = CALIBRATION_PANEL_HEIGHT
        panel_x = (self.width - panel_width) // 2
        panel_y = CALIBRATION_PANEL_Y

        overlay = frame.copy()
        cv2.rectangle(
            overlay,
            (panel_x, panel_y),
            (panel_x + panel_width, panel_y + panel_height),
            COLOR_OVERLAY_BG,
            -1,
        )
        cv2.addWeighted(
            overlay,
            CALIBRATION_OVERLAY_ALPHA,
            frame,
            1 - CALIBRATION_OVERLAY_ALPHA,
            0,
            frame,
        )

        cv2.rectangle(
            frame,
            (panel_x, panel_y),
            (panel_x + panel_width, panel_y + panel_height),
            COLOR_WARNING,
            CALIBRATION_PANEL_BORDER_THICKNESS,
        )

        if not person_present:
            cv2.putText(
                frame,
                "No Person Detected",
                (
                    panel_x + CALIBRATION_PANEL_PADDING,
                    panel_y + CALIBRATION_TEXT_Y_OFFSET,
                ),
                cv2.FONT_HERSHEY_DUPLEX,
                FONT_SCALE_LARGE,
                COLOR_TEXT,
                FONT_THICKNESS_BOLD,
                cv2.LINE_AA,
            )

            cv2.putText(
                frame,
                "Please sit in front of the camera",
                (
                    panel_x + CALIBRATION_PANEL_PADDING,
                    panel_y + CALIBRATION_SUBTEXT_Y_OFFSET,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                FONT_SCALE_SMALL,
                COLOR_GRAY_LIGHT,
                FONT_THICKNESS_NORMAL,
                cv2.LINE_AA,
            )
        elif progress == -1:
            cv2.putText(
                frame,
                "Waiting to Calibrate",
                (
                    panel_x + CALIBRATION_PANEL_PADDING,
                    panel_y + CALIBRATION_TEXT_Y_OFFSET,
                ),
                cv2.FONT_HERSHEY_DUPLEX,
                FONT_SCALE_LARGE,
                COLOR_TEXT,
                FONT_THICKNESS_BOLD,
                cv2.LINE_AA,
            )

            cv2.putText(
                frame,
                "Sit up straight to begin!",
                (
                    panel_x + CALIBRATION_PANEL_PADDING,
                    panel_y + CALIBRATION_SUBTEXT_Y_OFFSET,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                FONT_SCALE_SMALL,
                COLOR_GRAY_LIGHT,
                FONT_THICKNESS_NORMAL,
                cv2.LINE_AA,
            )
        else:
            cv2.putText(
                frame,
                "Calibrating...",
                (
                    panel_x + CALIBRATION_PANEL_PADDING,
                    panel_y + CALIBRATION_TEXT_Y_OFFSET,
                ),
                cv2.FONT_HERSHEY_DUPLEX,
                FONT_SCALE_LARGE,
                COLOR_TEXT,
                FONT_THICKNESS_BOLD,
                cv2.LINE_AA,
            )

            cv2.putText(
                frame,
                "Please sit naturally and look at your desk",
                (
                    panel_x + CALIBRATION_PANEL_PADDING,
                    panel_y + CALIBRATION_SUBTEXT_Y_OFFSET,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                FONT_SCALE_SMALL,
                COLOR_GRAY_LIGHT,
                FONT_THICKNESS_NORMAL,
                cv2.LINE_AA,
            )

            bar_x = panel_x + CALIBRATION_PANEL_PADDING
            bar_y = panel_y + CALIBRATION_BAR_Y_OFFSET
            bar_width = panel_width - CALIBRATION_BAR_MARGIN
            bar_height = CALIBRATION_BAR_HEIGHT

            cv2.rectangle(
                frame,
                (bar_x, bar_y),
                (bar_x + bar_width, bar_y + bar_height),
                COLOR_GRAY_DARK,
                -1,
            )

            fill_width = int(bar_width * progress)
            cv2.rectangle(
                frame,
                (bar_x, bar_y),
                (bar_x + fill_width, bar_y + bar_height),
                COLOR_WARNING,
                -1,
            )

            progress_text = f"{int(progress * PERCENT_MULTIPLIER)}%"
            cv2.putText(
                frame,
                progress_text,
                (
                    bar_x + bar_width + CALIBRATION_PROGRESS_TEXT_X_OFFSET,
                    bar_y + CALIBRATION_PROGRESS_TEXT_Y_OFFSET,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                FONT_SCALE_SMALL,
                COLOR_TEXT,
                FONT_THICKNESS_NORMAL,
                cv2.LINE_AA,
            )

    def _draw_top_bar(self, frame, duration):
        overlay = frame.copy()
        bar_height = TOP_BAR_HEIGHT
        cv2.rectangle(overlay, (0, 0), (self.width, bar_height), COLOR_OVERLAY_BG, -1)
        cv2.addWeighted(
            overlay, TOP_BAR_OVERLAY_ALPHA, frame, 1 - TOP_BAR_OVERLAY_ALPHA, 0, frame
        )

        cv2.putText(
            frame,
            "KID-WATCH v0.1",
            (TOP_BAR_TITLE_X, TOP_BAR_TITLE_Y),
            cv2.FONT_HERSHEY_DUPLEX,
            FONT_SCALE_TITLE,
            COLOR_TEXT,
            FONT_THICKNESS_BOLD,
            cv2.LINE_AA,
        )

        cv2.putText(
            frame,
            "Study Session Monitor",
            (TOP_BAR_TITLE_X, TOP_BAR_SUBTITLE_Y),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_SMALL,
            COLOR_GRAY_MEDIUM,
            FONT_THICKNESS_NORMAL,
            cv2.LINE_AA,
        )

        time_str = f"Session: {format_duration(duration)}"
        cv2.putText(
            frame,
            time_str,
            (self.width - TOP_BAR_SESSION_X_OFFSET, TOP_BAR_SESSION_Y),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_MEDIUM,
            COLOR_TEXT,
            FONT_THICKNESS_BOLD,
            cv2.LINE_AA,
        )

    def _draw_status_panel(self, frame, state, focus_score, phone_count, slouch_count):
        """Draw right-side status panel."""
        panel_width = STATUS_PANEL_WIDTH
        panel_x = self.width - panel_width - STATUS_PANEL_MARGIN
        panel_y = STATUS_PANEL_Y

        overlay = frame.copy()
        cv2.rectangle(
            overlay,
            (panel_x, panel_y),
            (panel_x + panel_width, panel_y + STATUS_PANEL_HEIGHT),
            COLOR_OVERLAY_BG,
            -1,
        )
        cv2.addWeighted(
            overlay,
            STATUS_PANEL_OVERLAY_ALPHA,
            frame,
            1 - STATUS_PANEL_OVERLAY_ALPHA,
            0,
            frame,
        )

        if "STUDYING" in state:
            border_color = COLOR_STUDYING
        elif "DISTRACTED" in state:
            border_color = COLOR_DISTRACTED
        else:
            border_color = COLOR_WARNING

        cv2.rectangle(
            frame,
            (panel_x, panel_y),
            (panel_x + panel_width, panel_y + STATUS_PANEL_HEIGHT),
            border_color,
            STATUS_PANEL_BORDER_THICKNESS,
        )

        y_offset = panel_y + STATUS_HEADER_Y_OFFSET

        cv2.putText(
            frame,
            "STATUS",
            (panel_x + STATUS_PANEL_PADDING, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_LABEL,
            COLOR_GRAY_LIGHT,
            FONT_THICKNESS_NORMAL,
            cv2.LINE_AA,
        )
        y_offset += STATUS_STATE_HEADER_SPACING

        state_lines = state.split(" - ")
        for line in state_lines:
            cv2.putText(
                frame,
                line,
                (panel_x + STATUS_PANEL_PADDING, y_offset),
                cv2.FONT_HERSHEY_DUPLEX,
                FONT_SCALE_LARGE,
                border_color,
                FONT_THICKNESS_BOLD,
                cv2.LINE_AA,
            )
            y_offset += STATUS_STATE_LINE_SPACING

        y_offset += STATUS_SECTION_SPACING

        cv2.putText(
            frame,
            "FOCUS SCORE",
            (panel_x + STATUS_PANEL_PADDING, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_LABEL,
            COLOR_GRAY_LIGHT,
            FONT_THICKNESS_NORMAL,
            cv2.LINE_AA,
        )
        y_offset += STATUS_LABEL_SPACING

        bar_width = FOCUS_BAR_WIDTH
        bar_height = FOCUS_BAR_HEIGHT
        bar_x = panel_x + STATUS_PANEL_PADDING

        cv2.rectangle(
            frame,
            (bar_x, y_offset - FOCUS_BAR_Y_ADJUST),
            (bar_x + bar_width, y_offset - FOCUS_BAR_Y_ADJUST + bar_height),
            COLOR_GRAY_DARK,
            -1,
        )

        fill_width = int(bar_width * (focus_score / PERCENT_MULTIPLIER))
        if focus_score >= FOCUS_SCORE_HIGH_THRESHOLD:
            fill_color = COLOR_STUDYING
        elif focus_score >= FOCUS_SCORE_MEDIUM_THRESHOLD:
            fill_color = COLOR_WARNING
        else:
            fill_color = COLOR_DISTRACTED

        cv2.rectangle(
            frame,
            (bar_x, y_offset - FOCUS_BAR_Y_ADJUST),
            (bar_x + fill_width, y_offset - FOCUS_BAR_Y_ADJUST + bar_height),
            fill_color,
            -1,
        )

        score_text = f"{focus_score:.1f}%"
        cv2.putText(
            frame,
            score_text,
            (bar_x + bar_width + FOCUS_SCORE_X_OFFSET, y_offset - FOCUS_SCORE_Y_ADJUST),
            cv2.FONT_HERSHEY_DUPLEX,
            FONT_SCALE_MEDIUM,
            COLOR_TEXT,
            FONT_THICKNESS_BOLD,
            cv2.LINE_AA,
        )

        y_offset += STATUS_SCORE_SPACING

        cv2.putText(
            frame,
            "ALERTS",
            (panel_x + STATUS_PANEL_PADDING, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_LABEL,
            COLOR_GRAY_LIGHT,
            FONT_THICKNESS_NORMAL,
            cv2.LINE_AA,
        )
        y_offset += STATUS_LABEL_SPACING

        cv2.putText(
            frame,
            f"Phone Pickups:  {phone_count}",
            (panel_x + STATUS_PANEL_PADDING, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_LABEL,
            COLOR_TEXT,
            FONT_THICKNESS_NORMAL,
            cv2.LINE_AA,
        )
        y_offset += STATUS_ALERT_LINE_SPACING

        cv2.putText(
            frame,
            f"Posture Alerts: {slouch_count}",
            (panel_x + STATUS_PANEL_PADDING, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_LABEL,
            COLOR_TEXT,
            FONT_THICKNESS_NORMAL,
            cv2.LINE_AA,
        )

    def _draw_debug_info(
        self,
        frame,
        iris_ratio,
        posture_metrics,
        action_label=None,
        action_confidence=None,
    ):
        debug_x = DEBUG_PANEL_X
        debug_y = DEBUG_PANEL_Y

        lines = []

        if action_label is not None:
            action_text = f"ACTION: {action_label}"
            action_color = (
                COLOR_STUDYING if action_label == "studying" else COLOR_WARNING
            )
            lines.append((action_text, action_color))

            if action_confidence is not None:
                conf_text = f"Confidence: {action_confidence:.2f}"
                conf_color = (
                    COLOR_STUDYING
                    if action_confidence > DEBUG_ACTION_CONFIDENCE_THRESHOLD
                    else COLOR_WARNING
                )
                lines.append((conf_text, conf_color))

        if iris_ratio is not None:
            iris_text = f"Iris Ratio: {iris_ratio:.3f}"
            iris_color = (
                COLOR_STUDYING
                if iris_ratio > DEBUG_IRIS_RATIO_THRESHOLD
                else COLOR_WARNING
            )
            lines.append((iris_text, iris_color))

        if posture_metrics is not None:
            if posture_metrics.get("neck_angle") is not None:
                neck_angle = posture_metrics["neck_angle"]
                neck_text = f"Neck Angle: {neck_angle:.1f}°"
                neck_color = (
                    COLOR_STUDYING
                    if neck_angle > DEBUG_NECK_ANGLE_GOOD
                    else (
                        COLOR_WARNING
                        if neck_angle > DEBUG_NECK_ANGLE_WARNING
                        else COLOR_DISTRACTED
                    )
                )
                lines.append((neck_text, neck_color))

            if posture_metrics.get("back_angle") is not None:
                back_angle = posture_metrics["back_angle"]
                back_text = f"Back Angle: {back_angle:.1f}°"
                back_color = (
                    COLOR_STUDYING
                    if back_angle > DEBUG_BACK_ANGLE_GOOD
                    else (
                        COLOR_WARNING
                        if back_angle > DEBUG_BACK_ANGLE_WARNING
                        else COLOR_DISTRACTED
                    )
                )
                lines.append((back_text, back_color))

            if posture_metrics.get("forward_head_ratio") is not None:
                fh_ratio = posture_metrics["forward_head_ratio"]
                fh_text = f"Fwd Head: {fh_ratio:.2f}x"
                fh_color = (
                    COLOR_STUDYING
                    if fh_ratio < DEBUG_FORWARD_HEAD_RATIO_THRESHOLD
                    else COLOR_WARNING
                )
                lines.append((fh_text, fh_color))

        if not lines:
            return

        panel_height = DEBUG_PANEL_BASE_HEIGHT + len(lines) * DEBUG_LINE_SPACING
        overlay = frame.copy()
        cv2.rectangle(
            overlay,
            (debug_x, debug_y),
            (debug_x + DEBUG_PANEL_WIDTH, debug_y + panel_height),
            COLOR_OVERLAY_BG,
            -1,
        )
        cv2.addWeighted(
            overlay,
            DEBUG_PANEL_OVERLAY_ALPHA,
            frame,
            1 - DEBUG_PANEL_OVERLAY_ALPHA,
            0,
            frame,
        )

        cv2.putText(
            frame,
            "DEBUG INFO",
            (debug_x + DEBUG_TEXT_PADDING, debug_y + DEBUG_HEADER_Y_OFFSET),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_SMALL,
            COLOR_GRAY_LIGHT,
            FONT_THICKNESS_NORMAL,
            cv2.LINE_AA,
        )

        y_offset = debug_y + DEBUG_CONTENT_Y_OFFSET
        for text, color in lines:
            cv2.putText(
                frame,
                text,
                (debug_x + DEBUG_TEXT_PADDING, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                FONT_SCALE_SMALL,
                color,
                FONT_THICKNESS_NORMAL,
                cv2.LINE_AA,
            )
            y_offset += DEBUG_LINE_SPACING

    def _draw_phone_box(self, frame, phone):
        """Draw bounding box around detected phone."""
        x1, y1, x2, y2 = phone["bbox"]
        confidence = phone["confidence"]

        cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_PHONE_BOX, PHONE_BOX_THICKNESS)

        label = f"PHONE {confidence:.0%}"
        label_size, _ = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE_LABEL, FONT_THICKNESS_BOLD
        )
        cv2.rectangle(
            frame,
            (x1, y1 - label_size[1] - PHONE_LABEL_BG_PADDING),
            (x1 + label_size[0] + PHONE_LABEL_BG_PADDING, y1),
            COLOR_PHONE_BOX,
            -1,
        )
        cv2.putText(
            frame,
            label,
            (x1 + PHONE_LABEL_TEXT_MARGIN, y1 - PHONE_LABEL_TEXT_MARGIN),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_LABEL,
            COLOR_TEXT,
            FONT_THICKNESS_BOLD,
            cv2.LINE_AA,
        )

    def _draw_controls_hint(self, frame):
        """Draw keyboard controls at bottom."""
        hints = "Controls: [Q]uit  [S]tart/Stop  [R]eset"
        text_size, _ = cv2.getTextSize(
            hints, cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE_SMALL, FONT_THICKNESS_NORMAL
        )
        x = (self.width - text_size[0]) // 2
        y = self.height - CONTROLS_HINT_BOTTOM_MARGIN

        cv2.putText(
            frame,
            hints,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            FONT_SCALE_SMALL,
            COLOR_GRAY_MEDIUM,
            FONT_THICKNESS_NORMAL,
            cv2.LINE_AA,
        )
