"""
KID-WATCH v0.1 — Utility Functions
Helper functions for model download, geometry calculations, and drawing
"""

import cv2
import numpy as np
import urllib.request
import os
from datetime import timedelta

from .config import COLOR_TEXT, COLOR_OVERLAY_BG, COLOR_SKELETON

# ============================================================================
# Module-level Constants
# ============================================================================

# Drawing and text rendering
DEFAULT_FONT_SCALE = 0.6
TEXT_BG_OVERLAY_ALPHA = 0.7
TEXT_BG_OVERLAY_COMPLEMENT = 0.3
TEXT_PADDING = 5
TEXT_RETURN_HEIGHT_OFFSET = 2

# Landmark visibility and detection
VISIBILITY_THRESHOLD = 0.5
LANDMARK_CIRCLE_RADIUS = 3
LANDMARK_CIRCLE_THICKNESS = -1

# Geometry calculations
ANGLE_CALCULATION_EPSILON = 1e-6
SKELETON_LINE_THICKNESS = 2

# Angle clipping bounds
COSINE_ANGLE_MIN = -1.0
COSINE_ANGLE_MAX = 1.0


def download_model(url, filename):
    """Download MediaPipe model if not exists."""
    if os.path.exists(filename):
        return filename

    print(f"Downloading {filename}...")
    try:
        urllib.request.urlretrieve(url, filename)
        print(f"✓ Downloaded {filename}")
        return filename
    except Exception as e:
        print(f"✗ Failed to download {filename}: {e}")
        raise


def calculate_angle(a, b, c):
    """Calculate angle ABC using three points (numpy arrays)."""
    ba = a - b
    bc = c - b
    cosine_angle = np.dot(ba, bc) / (
        np.linalg.norm(ba) * np.linalg.norm(bc) + ANGLE_CALCULATION_EPSILON
    )
    angle = np.arccos(np.clip(cosine_angle, COSINE_ANGLE_MIN, COSINE_ANGLE_MAX))
    return np.degrees(angle)


def calculate_distance(p1, p2):
    """Euclidean distance between two points."""
    return np.linalg.norm(p1 - p2)


def draw_text_with_background(
    img,
    text,
    position,
    font_scale=DEFAULT_FONT_SCALE,
    thickness=2,
    text_color=COLOR_TEXT,
    bg_color=COLOR_OVERLAY_BG,
    padding=TEXT_PADDING,
):
    """Draw text with semi-transparent background for readability."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_width, text_height), baseline = cv2.getTextSize(
        text, font, font_scale, thickness
    )

    x, y = position
    overlay = img.copy()
    cv2.rectangle(
        overlay,
        (x - padding, y - text_height - padding),
        (x + text_width + padding, y + baseline + padding),
        bg_color,
        -1,
    )
    cv2.addWeighted(
        overlay, TEXT_BG_OVERLAY_ALPHA, img, TEXT_BG_OVERLAY_COMPLEMENT, 0, img
    )

    cv2.putText(img, text, (x, y), font, font_scale, text_color, thickness, cv2.LINE_AA)
    return text_height + baseline + TEXT_RETURN_HEIGHT_OFFSET * padding


def format_duration(seconds):
    """Format seconds into HH:MM:SS."""
    return str(timedelta(seconds=int(seconds)))


def draw_landmarks_on_image(bgr_image, detection_result):
    """Draw pose landmarks on image (manual implementation)."""
    if not detection_result or not detection_result.pose_landmarks:
        return

    h, w = bgr_image.shape[:2]

    # MediaPipe Pose connections (simplified - key body parts)
    POSE_CONNECTIONS = [
        (11, 12),
        (11, 13),
        (13, 15),
        (12, 14),
        (14, 16),  # Arms
        (11, 23),
        (12, 24),
        (23, 24),  # Torso
        (23, 25),
        (25, 27),
        (24, 26),
        (26, 28),  # Legs
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 7),
        (0, 4),
        (4, 5),
        (5, 6),
        (6, 8),  # Face
    ]

    for pose_landmarks in detection_result.pose_landmarks:
        # Draw connections
        for connection in POSE_CONNECTIONS:
            start_idx, end_idx = connection
            if start_idx < len(pose_landmarks) and end_idx < len(pose_landmarks):
                start = pose_landmarks[start_idx]
                end = pose_landmarks[end_idx]

                if (
                    start.visibility > VISIBILITY_THRESHOLD
                    and end.visibility > VISIBILITY_THRESHOLD
                ):
                    start_point = (int(start.x * w), int(start.y * h))
                    end_point = (int(end.x * w), int(end.y * h))
                    cv2.line(
                        bgr_image,
                        start_point,
                        end_point,
                        COLOR_SKELETON,
                        SKELETON_LINE_THICKNESS,
                    )

        # Draw landmarks
        for landmark in pose_landmarks:
            if landmark.visibility > VISIBILITY_THRESHOLD:
                x = int(landmark.x * w)
                y = int(landmark.y * h)
                cv2.circle(
                    bgr_image,
                    (x, y),
                    LANDMARK_CIRCLE_RADIUS,
                    COLOR_SKELETON,
                    LANDMARK_CIRCLE_THICKNESS,
                )
