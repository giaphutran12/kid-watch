"""
KID-WATCH v0.1 — Detectors Package
Exports all detector classes
"""

from kid_watch.config import USE_ML_DETECTOR

if USE_ML_DETECTOR:
    from .posture_detector_yolo import YoloPoseDetector
    from .movinet_detector import MoViNetDetector
    from .state_machine import DetectionStateMachine
    from .gaze_detector import GazeDetector

    __all__ = [
        "YoloPoseDetector",
        "MoViNetDetector",
        "DetectionStateMachine",
        "GazeDetector",
        "PhoneDetector",
    ]
else:
    from .posture_detector import PostureDetector
    from .gaze_detector import GazeDetector
    from .study_detector import StudyDetector

    __all__ = [
        "PostureDetector",
        "GazeDetector",
        "StudyDetector",
        "PhoneDetector",
    ]

from .phone_detector import PhoneDetector
