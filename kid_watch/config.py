"""
KID-WATCH v0.1 — Configuration Constants
All thresholds, colors, and model URLs
"""

# Video settings
CAMERA_INDEX = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
TARGET_FPS = 30

# Detection thresholds
POSTURE_ANGLE_THRESHOLD = 25
GAZE_DOWN_PITCH_THRESHOLD = 15
GAZE_AWAY_YAW_THRESHOLD = 55
PHONE_CONFIDENCE_THRESHOLD = 0.55
POSE_CONFIDENCE_THRESHOLD = 0.5

# Temporal smoothing (avoid flickering)
STATE_HISTORY_SIZE = 15
PHONE_DETECTION_FRAMES = 5
SLOUCH_DETECTION_FRAMES = 30

# Scoring weights
WEIGHT_POSTURE = 0.35
WEIGHT_GAZE = 0.35
WEIGHT_NO_PHONE = 0.30

# UI Colors (BGR format)
COLOR_STUDYING = (0, 255, 0)
COLOR_WARNING = (0, 165, 255)
COLOR_DISTRACTED = (0, 0, 255)
COLOR_TEXT = (255, 255, 255)
COLOR_OVERLAY_BG = (40, 40, 40)
COLOR_PHONE_BOX = (0, 0, 255)
COLOR_SKELETON = (0, 255, 255)

# v0.3 ML Detector Configuration
USE_ML_DETECTOR = True  # Set False to use old MediaPipe pipeline

# MoViNet
MOVINET_MODEL_PATH = "models/movinet_a2_stream_v0.3"
MOVINET_SKIP_FRAMES = 5  # Run MoViNet every Nth frame for performance
MOVINET_CONFIDENCE_THRESHOLD = 0.4

# YOLOv8n-pose
YOLO_POSE_MODEL = "yolov8n-pose.pt"

# v0.3 scoring weights (gaze removed)
WEIGHT_POSTURE_V03 = 0.30
WEIGHT_STUDYING_CONFIDENCE = 0.40
WEIGHT_NO_PHONE_V03 = 0.30

# MediaPipe model URLs (legacy fallback mode)
POSE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
FACE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
