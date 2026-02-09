# KID-WATCH v0.1 — Study Session Monitor

**Production PoC for Viettel (700k home camera deployment)**

Real-time camera-based study monitoring system using computer vision and deep learning.

## Features

- **Posture Detection**: Monitors sitting posture using MediaPipe pose estimation (33 body keypoints)
- **Phone Detection**: Detects cell phone usage via YOLOv8 object detection
- **Gaze Tracking**: Estimates head pose and gaze direction using facial landmarks
- **Engagement Scoring**: Real-time focus score combining all signals
- **Session Reports**: Detailed analytics on study quality, distractions, and recommendations

## Demo Screenshot

When running, you'll see:
- Real-time video with skeleton overlay
- Status panel showing: STUDYING (green) / WARNING (yellow) / DISTRACTED (red)
- Focus score percentage with progress bar
- Phone pickup counter
- Posture alert counter
- Session timer
- FPS counter

## Requirements

- macOS 10.15+ (tested on macOS 26.2 with Apple M5)
- Python 3.13+
- Webcam with camera permissions enabled
- ~500MB disk space (for YOLO model)

## Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

```bash
# Activate virtual environment
source venv/bin/activate

# Run the application
python kid_watch.py
```

### Keyboard Controls

- **Q**: Quit and show session report
- **S**: Start/Stop session
- **R**: Reset session

### First Run

On first run:
1. YOLOv8n model will auto-download (~6MB)
2. macOS will request camera permissions - **GRANT ACCESS**
3. Session starts automatically

## Camera Permissions (macOS)

If you see "not authorized to capture video":

1. Open **System Settings** → **Privacy & Security** → **Camera**
2. Enable camera access for **Terminal** (or your Python IDE)
3. Restart the application

## Technical Architecture

```
Webcam Input (720p/1080p)
    ↓
┌─── Frame Processing Pipeline ───────────────────┐
│ 1. MediaPipe Pose → 33 keypoints → posture      │
│ 2. MediaPipe FaceMesh → head pose → gaze        │
│ 3. YOLOv8n → object detection → phone detected  │
│ 4. Engagement Engine → combine signals → score  │
│ 5. Dashboard Renderer → overlay on frame        │
└──────────────────────────────────────────────────┘
    ↓
Real-time OpenCV Display + Session Report
```

### Detection Logic

**Posture Detection**:
- Calculates ear-shoulder-hip alignment
- Forward lean > 15° = SLOUCHING
- Uses landmark visibility confidence to avoid false positives

**Gaze Estimation**:
- Estimates head pitch (up/down) and yaw (left/right)
- Looking down at desk = STUDYING
- Looking away/up = DISTRACTED

**Phone Detection**:
- YOLO detects COCO class 67 ("cell phone")
- Temporal smoothing (5 frames) to avoid false positives
- Tracks discrete pickup events (not continuous detection)

**Engagement Scoring**:
- Weighted combination: 35% posture + 35% gaze + 30% no-phone
- Rolling average over time
- 0-100% focus score

## Performance

- **Target**: 15+ FPS on Apple M5 MacBook
- **Actual**: 20-30 FPS (tested on M5 with 720p camera)
- **Optimizations**: YOLOv8n (nano model), MediaPipe model_complexity=1

## Session Report Example

```
======================================================================
KID-WATCH SESSION REPORT
======================================================================
Session Start:     2026-02-08 14:30:00
Session End:       2026-02-08 15:45:30
Total Duration:    01:15:30
----------------------------------------------------------------------
Focus Score:       78.5%
Phone Pickups:     3
Posture Alerts:    7
----------------------------------------------------------------------
STATE TIMELINE:
  [14:30:05] → STUDYING
  [14:42:18] → DISTRACTED - PHONE
  [14:43:02] → STUDYING
  [14:58:31] → WARNING - SLOUCHING
  [15:01:15] → STUDYING
  ... and 12 more state changes
----------------------------------------------------------------------
RECOMMENDATIONS:
  • Good session. Try to minimize phone distractions.
  • Adjust chair height and monitor position for better posture
======================================================================
```

## Deployment Notes (Viettel)

### Scalability
- Single-file Python application for easy deployment
- Minimal dependencies (4 packages)
- Auto-downloads YOLO model on first run
- No cloud dependencies (fully offline)

### Hardware Requirements
- CPU: Any modern ARM/x86 processor
- RAM: 2GB minimum, 4GB recommended
- Camera: 720p minimum, 1080p recommended
- Storage: 500MB for models + logs

### Configuration
All thresholds are configurable in `kid_watch.py`:
- `POSTURE_ANGLE_THRESHOLD`: Slouch sensitivity
- `GAZE_DOWN_PITCH_THRESHOLD`: Gaze detection sensitivity
- `PHONE_CONFIDENCE_THRESHOLD`: YOLO confidence threshold
- Scoring weights: `WEIGHT_POSTURE`, `WEIGHT_GAZE`, `WEIGHT_NO_PHONE`

### Future Enhancements
- [ ] Multi-person tracking
- [ ] Cloud analytics dashboard
- [ ] Mobile app for parents
- [ ] Screen content analysis (requires screen capture)
- [ ] Voice activity detection
- [ ] Break reminders and study timers

## Troubleshooting

**Camera not opening**:
- Check camera permissions in System Settings
- Ensure no other app is using the camera
- Try changing `CAMERA_INDEX` in code (0, 1, 2...)

**Low FPS**:
- Reduce resolution: `FRAME_WIDTH = 640`, `FRAME_HEIGHT = 480`
- Use YOLOv8n (already using the fastest model)
- Close other applications

**False phone detections**:
- Increase `PHONE_CONFIDENCE_THRESHOLD` (default: 0.4)
- Increase `PHONE_DETECTION_FRAMES` (default: 5)

**Posture too sensitive**:
- Increase `POSTURE_ANGLE_THRESHOLD` (default: 15)
- Increase `SLOUCH_DETECTION_FRAMES` (default: 30)

## License

Proprietary - Viettel PoC Demo

## Contact

For deployment questions: [Your contact info]
