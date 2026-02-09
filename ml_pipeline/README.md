# KID-WATCH ML Pipeline v0.3

Real-time study monitoring using a 3-model stack: YOLOv8n (phone), YOLOv8n-pose (posture), MoViNet-A2-Stream (action recognition).

## Architecture Overview

```
Input Frame (720p)
    ↓
┌─────────────────────────────────────────┐
│ YOLOv8n (Phone Detection)               │ ~31ms
│ YOLOv8n-pose (Posture/Keypoints)        │ ~33ms
│ MoViNet-A2-Stream (Action Recognition)  │ ~93ms (CPU-only)
└─────────────────────────────────────────┘
    ↓
State Machine (Debounced Transitions)
    ↓
Engagement Engine (Scoring)
    ↓
Output: STUDYING | SLEEPING | PHONE | SLOUCHING | DISTRACTED | AWAY
```

**Performance**: 82.7ms amortized latency with skip-frame strategy (MoViNet every 5th frame) → 12.1 FPS effective

## Data Sources

### Kinetics-700 Selective Download
- **Classes**: reading_book, reading_newspaper, writing, sleeping, yawning, other
- **Target**: 1,000 URLs per class (expect 50% success rate due to video age)
- **Result**: 1,493 total clips (437 reading_book, 192 reading_newspaper, 185 writing, 190 sleeping, 188 yawning, 301 other)
- **Size**: 1.1 GB total
- **Manifest**: `data/manifest.json` with SHA256 hashes for integrity verification

### Class Mapping
```python
studying   = reading_book + reading_newspaper + writing
sleeping   = sleeping + yawning
other      = random non-target Kinetics classes (neutral/negative)
```

## Training Instructions

### 1. Environment Setup
```bash
# Create isolated ML environment (Python 3.11)
python3.11 -m venv ml_venv
source ml_venv/bin/activate

# Install dependencies (order matters!)
pip install --upgrade pip
pip install numpy==1.26.4  # Pin first
pip install tensorflow==2.17.0 tensorflow-metal==1.2.0 tensorflow-hub
pip install torch torchvision ultralytics
pip install opencv-python==4.9.0.80  # NOT headless
pip install mediapipe yt-dlp pandas scikit-learn
pip install numpy==1.26.4 --force-reinstall  # Ensure numpy stays pinned
```

### 2. Download Data
```bash
python ml_pipeline/download_kinetics.py \
  --output-dir data/kinetics700 \
  --manifest-path data/manifest.json \
  --max-per-class 200 \
  --other-sample 300 \
  --workers 6
```

### 3. Preprocess
```bash
python ml_pipeline/preprocess.py \
  --input-dir data/kinetics700 \
  --output-dir data/processed \
  --fps 5 \
  --frames 50 \
  --size 172
```

Output: 1,493 clips → 24.68 GB processed data
- Train: 1,194 clips (80%)
- Val: 149 clips (10%)
- Test: 150 clips (10%)

### 4. Train
```bash
python ml_pipeline/train.py \
  --data-dir data/processed \
  --model-output models/movinet_a2_stream_v0.3 \
  --epochs-stage1 5 \
  --epochs-stage2 15 \
  --batch-size 4
```

**Training Strategy**:
- Stage 1: Head-only fine-tuning (frozen backbone, 5 epochs, lr=1e-3)
- Stage 2: Full fine-tuning (top 20% backbone, 15 epochs, lr=1e-4, cosine decay)

**Expected Results**:
- Stage 1 val_accuracy: >60%
- Stage 2 val_accuracy: >75%
- Per-class recall: studying >70%, sleeping >70%, other >60%

### 5. Evaluate
```bash
python ml_pipeline/evaluate.py \
  --model-path models/movinet_a2_stream_v0.3 \
  --data-dir data/processed
```

Output: `training_results/confusion_matrix.json`, `training_results/metrics.json`

## Model Versioning

**Scheme**: `movinet_a2_stream_v{major}.{minor}_{date}_{dataset_hash}`

Example: `movinet_a2_stream_v0.3_20260208_abc123def456`

- **major.minor**: Release version (0.3 = first production release)
- **date**: Training date (YYYYMMDD)
- **dataset_hash**: SHA256 of manifest.json (ensures reproducibility)

## Inference

### Per-Frame Inference
```python
from kid_watch.detectors.movinet_detector import MoViNetDetector
from kid_watch.detectors.posture_detector_yolo import YoloPoseDetector
from kid_watch.detectors.phone_detector import PhoneDetector

movinet = MoViNetDetector(model_path="models/movinet_a2_stream_v0.3")
pose = YoloPoseDetector()
phone = PhoneDetector()

# Every frame
phone_detected = phone.detect(frame)
posture_good, metrics, _ = pose.detect(frame)

# Every 5th frame (skip-frame strategy)
if frame_count % 5 == 0:
    action, confidence, _ = movinet.detect(frame)
else:
    action = "other"  # Reuse previous prediction
```

### Skip-Frame Strategy
- **Why**: MoViNet at 93ms/frame is the bottleneck
- **Solution**: Run MoViNet every 5th frame only
- **Result**: 82.7ms amortized latency (4×64ms YOLO + 1×156ms all) / 5 = 12.1 FPS
- **Tradeoff**: Action recognition updates every 167ms (acceptable for study monitoring)

### State Machine
Temporal debouncing with frame counters:
- **STUDYING**: 3 consecutive "studying" predictions
- **SLEEPING**: 3 consecutive "sleeping" predictions
- **DISTRACTED**: 8 seconds of "other" predictions (temporal, not raw confidence)
- **PHONE**: Immediate (YOLO has built-in smoothing)
- **SLOUCHING**: 30 frames of bad posture
- **AWAY**: 3 seconds without person detection

## Known Limitations

### Domain Gap
- **Training data**: YouTube clips + classroom footage (Kinetics-700)
- **Deployment**: Home cameras with different lighting, angles, backgrounds
- **Impact**: May have lower accuracy on home camera footage
- **Mitigation**: Collect 200+ in-domain clips for fine-tuning in v0.4

### Single Person Only
- Assumes one child per frame
- If multiple people detected: uses largest bounding box
- Multi-person support deferred to v0.4

### No Gaze Tracking
- Dropped MediaPipe FaceLandmarker entirely
- Engagement formula reweighted: posture(0.30) + studying_confidence(0.40) + no_phone(0.30)
- No replacement for gaze signal

### CPU-Only MoViNet
- TensorFlow 2.17 + tensorflow-metal 1.2.0 has Metal GPU XLA bug
- MoViNet forced to CPU mode at 93ms/frame
- GPU acceleration expected in TensorFlow 2.18+ (estimated 20-30ms/frame)

### FP32 Inference Only
- No INT8 quantization optimization
- Model size: ~100MB (manageable for local deployment)

### Full-Frame Processing
- MoViNet processes entire 172×172 frame (no person cropping)
- May classify background activity if person is small in frame
- Person cropping planned for v0.4

### Night/IR Mode Untested
- Model trained on RGB video only
- Behavior in night mode or infrared unknown

## Configuration

Key parameters in `kid_watch/config.py`:

```python
# MoViNet
MOVINET_MODEL_PATH = "models/movinet_a2_stream_v0.3"
MOVINET_CONFIDENCE_THRESHOLD = 0.4
MOVINET_SKIP_FRAMES = 5  # Run every 5th frame

# State Machine (frame counts at 30 FPS input)
STUDYING_ENTER_FRAMES = 3
STUDYING_EXIT_FRAMES = 5
SLEEPING_ENTER_FRAMES = 3
DISTRACTED_SECONDS = 8.0  # 240 frames @ 30 FPS
AWAY_SECONDS = 3.0  # 90 frames @ 30 FPS
SLOUCH_FRAMES = 30

# Engagement Scoring
WEIGHT_POSTURE = 0.30
WEIGHT_STUDYING_CONFIDENCE = 0.40
WEIGHT_NO_PHONE = 0.30
```

## Troubleshooting

**MoViNet model not found**:
- Check `models/movinet_a2_stream_v0.3/` exists
- Run training first: `python ml_pipeline/train.py`

**Low FPS (<10)**:
- Reduce `MOVINET_SKIP_FRAMES` from 5 to 10 (action updates every 333ms)
- Reduce input resolution to 480p
- Close other applications

**Poor accuracy on home camera**:
- Domain gap: model trained on YouTube, not home cameras
- Collect 200+ in-domain clips and fine-tune
- Adjust `MOVINET_CONFIDENCE_THRESHOLD` (default 0.4)

**Memory issues during training**:
- Reduce batch size: `--batch-size 2`
- Use gradient accumulation: `--accumulation-steps 2`
- Reduce `--epochs-stage2` from 15 to 10

## References

- **MoViNet paper**: https://arxiv.org/abs/2103.11511
- **TensorFlow Hub**: https://tfhub.dev/tensorflow/movinet/a2/stream/kinetics-600/classification/3
- **Ultralytics YOLO**: https://docs.ultralytics.com/
- **Kinetics-700**: https://deepmind.com/research/open-source/kinetics
