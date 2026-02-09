# ML Virtual Environment Setup — Python 3.11

## Overview
Unified Python 3.11 virtual environment (`ml_venv/`) containing ALL dependencies for:
- ML pipeline (TensorFlow, PyTorch, Ultralytics, MoViNet)
- App runtime (OpenCV, MediaPipe, NumPy)
- Data processing (Pandas, yt-dlp)

## Quick Start

### Activate the Environment
```bash
source ml_venv/bin/activate
```

### Verify Installation
```bash
python -c "import tensorflow, torch, ultralytics, cv2, numpy, mediapipe; print('✓ All OK')"
```

## Environment Details

### Location
- **Path**: `/Users/edwardtran/BLI/kid-watch/ml_venv/`
- **Python**: 3.11.14
- **Size**: ~2.1GB

### Installed Packages (69 total)
See `ml_requirements.txt` for complete list.

**Key ML Packages:**
- TensorFlow 2.17.0 + tensorflow-metal 1.2.0 (GPU acceleration)
- PyTorch 2.10.0 (with MPS support)
- Ultralytics 8.4.12 (YOLOv8)
- MediaPipe 0.10.32
- OpenCV 4.9.0.80
- NumPy 1.26.4 (pinned for TensorFlow compatibility)

**Data Processing:**
- Pandas 3.0.0
- yt-dlp 2026.2.4
- SciPy 1.17.0

## Critical Version Pins

**DO NOT UPGRADE THESE:**
- `numpy==1.26.4` — TensorFlow 2.17 requires <2.0
- `opencv-python==4.9.0.80` — Last version compatible with numpy 1.26.4
- `tensorflow==2.17.0` — Metal GPU support requires this version

## Troubleshooting

### NumPy Version Mismatch
If you see: `tensorflow 2.17.0 requires numpy<2.0.0`

**Fix:**
```bash
source ml_venv/bin/activate
pip install numpy==1.26.4 --force-reinstall
```

### OpenCV Import Errors
If you see: `AttributeError: module 'cv2' has no attribute 'imshow'`

**Cause**: opencv-python-headless was installed (missing GUI functions)

**Fix:**
```bash
source ml_venv/bin/activate
pip uninstall opencv-python-headless -y
pip install opencv-python==4.9.0.80
```

### TensorFlow GPU Not Detected
If you see: `No GPU devices found`

**Note**: Metal GPU has XLA platform registration issue in TensorFlow 2.17
- Workaround: `tf.config.set_visible_devices([], 'GPU')` before loading models
- Expected fix: TensorFlow 2.18+ or tensorflow-metal 1.3.0+

## Reproducing This Environment

To recreate this venv on another machine:

```bash
# Create venv
/opt/homebrew/bin/python3.11 -m venv ml_venv

# Activate
source ml_venv/bin/activate

# Install from requirements
pip install -r ml_requirements.txt

# Verify
python -c "import tensorflow, torch, ultralytics, cv2, numpy, mediapipe; print('✓ OK')"
```

## Git Ignore
`ml_venv/` is in `.gitignore` — it will NOT be committed to the repository.

To share this environment:
1. Commit `ml_requirements.txt` to git
2. Others run: `pip install -r ml_requirements.txt`

## Next Steps
- Phase 1: Kinetics-700 dataset download
- Phase 2: MoViNet-A2 streaming inference
- Phase 3: Integration with YOLOv8 pipeline
