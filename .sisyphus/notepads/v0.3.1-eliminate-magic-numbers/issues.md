# v0.3.1 Magic Number Elimination — Issues

## [2026-02-09] Pre-existing LSP Errors (NOT caused by us)
- phone_detector.py: YOLO import warning (ultralytics typing issue — works at runtime)
- posture_detector_yolo.py: Same YOLO import warning
- movinet_detector.py: tensorflow_hub import (only available in ml_venv)
- kid_watch.py: Multiple "possibly unbound" warnings (conditional imports, works at runtime)
- ml_pipeline/preprocess.py: sklearn import (only in ml_venv)
- These are ALL pre-existing. Do NOT try to fix them during this refactoring.
