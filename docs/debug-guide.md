# KID-WATCH v0.3 — Debug Log Guide & System Architecture

**For:** First-time ML practitioners who want to understand what's happening under the hood.

**Purpose:** This guide explains every log line, every CSV column, and the complete pipeline that turns a camera frame into a "STUDYING" or "NOT STUDYING" verdict.

---

## Part 1: Reading Terminal Debug Logs

Every log line tells you something specific about what the system is doing. Here's how to read them.

### [ML] Lines — MoViNet Action Recognition Output

These appear roughly every 5 frames (since MoViNet runs every 5th frame).

**Format:**
```
[ML] action=studying conf=0.76 state=studying person=True
```

**What each part means:**

| Part | Example | Meaning |
|------|---------|---------|
| `action` | `studying` | MoViNet's raw prediction: what activity did it see? Options: `studying`, `sleeping`, `other` |
| `conf` | `0.76` | Confidence after EMA smoothing (0.0 to 1.0). Higher = more certain. Below 0.4 → defaults to "other" |
| `state` | `studying` | State machine's current decision (what gets displayed). Can differ from `action` due to debouncing |
| `person` | `True` | Did YOLO detect a person in the frame? `True` = yes, `False` = nobody visible |

**Real examples:**

```
[ML] action=studying conf=0.82 state=studying person=True
     ↑ MoViNet saw studying activity with 82% confidence, state machine agrees, person is visible
     
[ML] action=other conf=0.35 state=distracted person=True
     ↑ MoViNet saw something else (low confidence), state machine says DISTRACTED, person visible
     
[ML] action=sleeping conf=0.91 state=sleeping person=True
     ↑ MoViNet is very confident (91%) the person is sleeping
```

**What to look for:**
- If `action=other` but you're studying → domain gap issue (model trained on YouTube, not webcam)
- If `conf` is very low (< 0.3) → MoViNet is uncertain, probably defaulting to "other"
- If `person=False` → YOLO lost track of the person (they left, turned away, or lighting changed)

---

### [CAL POS] Lines — Calibration Position Change Detection

These appear when the system is checking if you've moved significantly (which would require recalibration).

**Format:**
```
[CAL POS] x_change=0.0594 y_change=0.0570 consecutive=1/15
```

**What each part means:**

| Part | Example | Meaning |
|------|---------|---------|
| `x_change` | `0.0594` | Horizontal movement as % of frame width (0.0 = no movement, 1.0 = full width) |
| `y_change` | `0.0570` | Vertical movement as % of frame height (0.0 = no movement, 1.0 = full height) |
| `consecutive` | `1/15` | Consecutive frames above threshold / frames needed to trigger recalibration. Need 15/15 to recalibrate |

**How it works:**
- Tracks your shoulder midpoint (center between left and right shoulders)
- If either x_change > 5% OR y_change > 8% → counts as a "movement frame"
- After 15 consecutive movement frames → triggers recalibration
- Resets to 0/15 if you stay still for even one frame

**Real examples:**

```
[CAL POS] x_change=0.0012 y_change=0.0008 consecutive=0/15
          ↑ Tiny movement, below threshold, counter resets to 0/15
          
[CAL POS] x_change=0.0823 y_change=0.0342 consecutive=5/15
          ↑ Significant horizontal movement, above 5% threshold, counting up
          
[CAL POS] x_change=0.1204 y_change=0.0956 consecutive=15/15
          ↑ Large movement for 15 frames straight → RECALIBRATION TRIGGERED
```

**What to look for:**
- If consecutive keeps resetting (never reaches 15/15) → you're moving slightly but not enough to trigger
- If it hits 15/15 while you're sitting still → calibration is too sensitive (known issue when slouching)
- If it never triggers even when you move → YOLO lost pose detection (can't track shoulder midpoint)

---

### [CAL DEBUG] Lines — Calibration Progress

These appear during the calibration phase, showing how many samples have been collected.

**Format:**
```
[CAL DEBUG] 5.3s | frames=43 pose_ok=43(100%) called=43 accepted=29 | REJECTS: no_posture=8 no_neck_fwd=0 neck=0 back=0 fwd_lean=0
```

**What each part means:**

| Part | Example | Meaning |
|------|---------|---------|
| Time | `5.3s` | Elapsed time since calibration started |
| `frames` | `43` | Total frames processed since calibration started |
| `pose_ok` | `43(100%)` | Frames where YOLO detected pose (17+ keypoints). `(100%)` = all frames had pose |
| `called` | `43` | MoViNet calls made (roughly every 5 frames, so ~43 frames = ~8-9 calls) |
| `accepted` | `29` | Samples that passed ALL quality checks and were used for baseline |
| `REJECTS` | (see below) | Why samples were rejected |

**Rejection reasons:**

| Reason | Meaning |
|--------|---------|
| `no_posture` | YOLO couldn't detect pose (not enough keypoints) |
| `no_neck_fwd` | Neck angle couldn't be computed (ears not visible) |
| `neck` | Neck angle was too extreme (not good posture) |
| `back` | Back angle was too extreme (slouching) |
| `fwd_lean` | Head was too far forward (slouching) |

**Real examples:**

```
[CAL DEBUG] 2.1s | frames=21 pose_ok=21(100%) called=4 accepted=18 | REJECTS: no_posture=0 no_neck_fwd=0 neck=0 back=0 fwd_lean=3
            ↑ Good calibration: 21 frames, 18 accepted, only 3 rejected for forward lean
            
[CAL DEBUG] 8.5s | frames=85 pose_ok=42(49%) called=17 accepted=12 | REJECTS: no_posture=30 no_neck_fwd=0 neck=0 back=0 fwd_lean=43
            ↑ Bad calibration: only 49% pose detection, many rejects for forward lean (slouching)
```

**What to look for:**
- `pose_ok < 80%` → lighting/angle issue, YOLO can't see your keypoints
- `accepted < 20` → you're not sitting still with good posture (too much slouching/movement)
- `fwd_lean` rejections → you're leaning forward, sit back more
- `no_posture` rejections → YOLO can't detect you, check lighting and camera angle

---

### [CAL FINALIZE] Lines — Calibration Completion

Appears when calibration finishes successfully.

**Format:**
```
[CAL FINALIZE] samples=45/30 elapsed=10.1s rate=4.5/s
```

**What each part means:**

| Part | Example | Meaning |
|------|---------|---------|
| `samples` | `45/30` | Accepted samples / minimum required (30). Need at least 30 to complete |
| `elapsed` | `10.1s` | Total calibration time |
| `rate` | `4.5/s` | Samples accepted per second (higher = better, means good posture detected consistently) |

**Real examples:**

```
[CAL FINALIZE] samples=35/30 elapsed=7.2s rate=4.9/s
               ↑ Good: 35 samples in 7.2 seconds, fast rate
               
[CAL FINALIZE] samples=30/30 elapsed=15.3s rate=2.0/s
               ↑ Barely passed: exactly 30 samples, took longer, slower rate
```

**What to look for:**
- `rate < 2.0/s` → you were moving or slouching frequently during calibration
- `samples` close to 30 → barely passed, calibration may be fragile
- If calibration never reaches 30 samples → you're not sitting still enough

---

### [CAL] Status Lines — Calibration State Changes

These appear when the calibration system changes states.

**Format examples:**

```
[CAL] Good posture detected for 1.5s, starting calibration!
      ↑ You sat still with good posture for 1.5 seconds, system is now collecting baseline samples
      
✓ Calibration complete!
  ↑ Baseline established, system is now in ACTIVE mode
  
⚠ Position change detected, recalibrating...
  ↑ You moved significantly, system is re-establishing baseline
  
[CAL] Bad posture during calibration for >2.0s, resetting to waiting
      ↑ You slouched while calibrating, had to restart from scratch
```

**What to look for:**
- If you see "resetting to waiting" frequently → you're moving or slouching too much
- If "Position change detected" appears while you're sitting still → calibration is too sensitive
- If calibration never completes → check the [CAL DEBUG] lines for what's being rejected

---

### [MOVINET] Lines — MoViNet Internal Events

These appear when MoViNet's internal state changes.

**Format examples:**

```
[MOVINET] Periodic state reset (10.0s elapsed)
          ↑ MoViNet's internal memory was cleared (happens every 10 seconds automatically)
          ↑ This is normal and expected
          
[MOVINET] Saturation watchdog: conf=0.99 for 2.1s, resetting state
          ↑ Confidence was stuck at 99% for too long, system forced a reset
          ↑ Prevents the model from getting "stuck" on one prediction
          
[MOVINET] Resetting streaming state
          ↑ Full reset of MoViNet's internal memory
          ↑ Happens when person disappears or system needs a fresh start
```

**What to look for:**
- "Saturation watchdog" → confidence was too high for too long (rare, usually means model is very certain)
- "Resetting streaming state" → person left the frame or system lost track

---

### [DEBUG] Lines — CSV Logging Events

These appear when CSV logging starts or stops.

**Format examples:**

```
[DEBUG] CSV logging started → debug_log_20250209_143022.csv
        ↑ CSV file created with this timestamp
        ↑ Only appears after first successful calibration
        
[DEBUG] CSV logging stopped
        ↑ CSV logging paused (usually during recalibration)
```

**What to look for:**
- If you never see "CSV logging started" → calibration never completed
- If you see "stopped" frequently → system is recalibrating often

---

## Part 2: Reading CSV Debug Logs

The CSV file contains one row per frame, with detailed metrics. Here's what each column means.

**File location:** `debug_log_YYYYMMDD_HHMMSS.csv` (created in the app directory after first calibration)

### Column Reference

| Column | Type | What It Means | Good Values | Bad Values |
|--------|------|--------------|-------------|------------|
| `timestamp` | float | Unix epoch (seconds since 1970-01-01) | Any increasing number | Gaps = dropped frames |
| `frame` | int | Frame counter since app started | Incrementing by 1 | Gaps = dropped frames |
| `state` | string | **What's displayed on screen** — the final verdict | "STUDYING", "SLEEPING", "SLOUCHING", "DISTRACTED", "PHONE", "AWAY" | N/A |
| `source` | string | MoViNet's raw action prediction (before state machine) | "studying", "sleeping", "other" | N/A |
| `studying` | float | **Confidence of the MoViNet prediction** (0.0 to 1.0) — MISLEADING NAME: it's the confidence regardless of which action was predicted | > 0.5 when source="studying" | Any value when source="other" |
| `person_present` | bool | Did YOLO detect a person? | True | False = nobody visible |
| `neck_flex` | float | (Currently unused in ML mode) | Empty | N/A |
| `forward_lean` | float | Degrees — how far is your head in front of your shoulders? | 0-10° = good posture | > 15° = slouching, Empty = YOLO couldn't detect |
| `pitch` | float | (Currently unused in ML mode) | Empty | N/A |
| `yaw` | float | (Currently unused in ML mode) | Empty | N/A |
| `gaze_at_desk` | float | (Currently unused in ML mode) | Empty | N/A |
| `posture_good` | bool | Is your posture acceptable? | True | False = slouching, Empty = couldn't detect |
| `phone_detected` | bool | Did YOLOv8n detect a phone? | False | True = phone visible |
| `focus_score` | float | Rolling engagement percentage (0-100%) | > 70% = good focus | < 50% = poor focus, 0.0 = calibrating |
| `camera_mode` | string | Which detector pipeline is active | "ml_detector" | "legacy" = old MediaPipe mode |

### Important Notes About the CSV

**Empty fields:**
- Empty fields mean YOLO-pose couldn't detect enough keypoints that frame
- Common causes: hand covering face, turned sideways, poor lighting, moving too fast
- The system continues with the last known value (doesn't crash)

**The `studying` column is confusing:**
- It's named `studying` but it's actually the **confidence of whatever action was predicted**
- If `source="sleeping"`, the `studying` column shows the confidence that it's sleeping
- If `source="other"`, the `studying` column shows the confidence that it's "other"
- It's NOT a boolean, it's a float (0.0 to 1.0)

**MoViNet runs every 5th frame:**
- MoViNet only runs every 5 frames (~93ms per call)
- Between calls, the same confidence value repeats for ~5 consecutive rows
- This is normal and expected

**focus_score = 0.0:**
- Does NOT mean focus is zero
- Means calibration is in progress (system doesn't score until calibration completes)
- Check the `state` column for "CALIBRATING"

### Real CSV Example

```
timestamp,frame,state,source,studying,person_present,neck_flex,forward_lean,pitch,yaw,gaze_at_desk,posture_good,phone_detected,focus_score,camera_mode
1707500422.1234,1,CALIBRATING,other,0.15,True,,,,,True,False,0.0,ml_detector
1707500422.1567,2,CALIBRATING,other,0.15,True,,,,,True,False,0.0,ml_detector
1707500422.1890,3,CALIBRATING,other,0.15,True,,,,,True,False,0.0,ml_detector
1707500422.2223,4,CALIBRATING,other,0.15,True,,,,,True,False,0.0,ml_detector
1707500422.2556,5,CALIBRATING,studying,0.82,True,,,,,True,False,0.0,ml_detector
1707500422.2889,6,STUDYING,studying,0.82,True,,,,,True,False,87.3,ml_detector
1707500422.3222,7,STUDYING,studying,0.82,True,,,,,True,False,88.1,ml_detector
1707500422.3555,8,STUDYING,studying,0.82,True,,,,,True,False,87.9,ml_detector
1707500422.3888,9,STUDYING,studying,0.82,True,,,,,True,False,88.5,ml_detector
1707500422.4221,10,STUDYING,other,0.35,True,,,,,True,False,72.4,ml_detector
1707500422.4554,11,STUDYING,other,0.35,True,,,,,True,False,71.2,ml_detector
1707500422.4887,12,DISTRACTED,other,0.35,True,,,,,True,False,45.3,ml_detector
```

**Reading this example:**

- Frames 1-5: Calibration in progress (`state=CALIBRATING`), focus_score = 0.0
- Frame 5: MoViNet predicts "studying" with 82% confidence
- Frames 6-9: State machine says STUDYING, focus_score rises to ~88%
- Frame 10: MoViNet switches to "other" (35% confidence)
- Frames 10-11: Still STUDYING (debounce: need 5 frames of NOT studying to exit)
- Frame 12: After enough "other" frames, state machine switches to DISTRACTED, focus_score drops to 45%

---

## Part 3: How KID-WATCH v0.3 Calculates Everything

This is the complete pipeline from camera frame to displayed state. Understanding this will help you debug any issue.

### Overview: The Full Pipeline

```
CAMERA (1280×720, ~30 FPS input)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  DETECTION PIPELINE (every frame, ~10 FPS effective)     │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────────────┐  ┌──────────────────┐              │
│  │ YOLOv8-Pose     │  │ YOLOv8n (phone)  │              │
│  │ (~33ms)         │  │ (~31ms)          │              │
│  └────────┬────────┘  └────────┬─────────┘              │
│           │                    │                        │
│           ▼                    │                        │
│  posture_good (T/F/None)       │                        │
│  forward_lean (degrees)        │                        │
│  pose_centroid (pixels)        │                        │
│           │         phone_detected (T/F)                │
│           │                    │                        │
│  ┌────────┴────────────────────┘                        │
│  │                                                      │
│  │  ┌──────────────────────┐ (every 5th frame)         │
│  │  │ MoViNet-A2-Stream    │                           │
│  │  │ (~93ms, CPU)         │                           │
│  │  └──────────┬───────────┘                           │
│  │             │                                       │
│  │    action (studying/sleeping/other)                 │
│  │    confidence (0.0-1.0, EMA smoothed)               │
│  │             │                                       │
│  ▼             ▼                                       │
│  ┌──────────────────────────┐                          │
│  │   STATE MACHINE          │                          │
│  │ (priority + debounce)    │                          │
│  └──────────┬───────────────┘                          │
│             │                                          │
│    state (STUDYING/SLEEPING/etc)                       │
│             │                                          │
│  ┌──────────┴──────────────┐                           │
│  │  ENGAGEMENT ENGINE      │                           │
│  │ 30% posture             │                           │
│  │ 40% studying_conf       │                           │
│  │ 30% no_phone            │                           │
│  └──────────┬──────────────┘                           │
│             │                                          │
│    focus_score (0-100%)                                │
│    display_state (GREEN/YELLOW/RED)                    │
└─────────────┬──────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────┐
│  CALIBRATION (runs in parallel)                          │
│                                                          │
│  WAITING → CALIBRATING → ACTIVE                         │
│                            │                             │
│  (monitors pose_centroid for position change)            │
│  (triggers recalibration if you move > 5% width/8% ht)   │
└──────────────────────────────────────────────────────────┘
              │
              ▼
         ┌──────────┐
         │ DASHBOARD │
         │ (OpenCV)  │
         └──────────┘
```

---

### Step 1: Camera Frame Capture

- Camera captures at **1280×720 resolution**
- Frames arrive at ~30 FPS from the camera
- Each frame is processed sequentially through the pipeline
- **Effective processing rate:** ~8-10 FPS (limited by MoViNet + YOLO processing time)

---

### Step 2: YOLOv8n-Pose → Posture Detection (EVERY frame)

**What it does:**
- Detects 17 COCO body keypoints: nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles
- Requires at least 7 visible keypoints with confidence > 0.3
- **Both ears must be visible** (otherwise can't compute head angle)

**What it computes:**

From the keypoints, it calculates three angles:

1. **forward_lean** = angle between ear-shoulder line and vertical
   - Measures how far your head is in front of your shoulders
   - 0° = head directly above shoulders (perfect)
   - 15° = head noticeably forward (slouching)
   - Computed from: left_ear, right_ear, left_shoulder, right_shoulder

2. **neck_angle** = angle at the shoulder
   - Computed from: ear → shoulder → hip vectors
   - Measures neck bend

3. **back_angle** = angle at the hip
   - Computed from: shoulder → hip → knee vectors
   - Measures back curvature

**Also extracts:**
- **pose_centroid** = midpoint of left and right shoulders (in pixel coordinates)
  - Used for position change detection during calibration

**Returns:**
- `posture_good`: True/False/None
  - True = all angles within acceptable range
  - False = at least one angle is too extreme (slouching)
  - None = couldn't detect enough keypoints
- `metrics`: dict with forward_lean, neck_angle, back_angle (or None if detection failed)
- `raw_result`: full YOLO output for debugging

**When it returns None:**
- Not enough keypoints detected (< 7 with confidence > 0.3)
- Ears not visible (can't compute head angle)
- That frame has no posture data in the CSV (empty fields)

**Real example:**

```
Frame 1: YOLO detects 15 keypoints, both ears visible
         → forward_lean=8.2°, neck_angle=12.1°, back_angle=5.3°
         → posture_good=True
         
Frame 2: YOLO detects 6 keypoints (not enough)
         → posture_good=None
         → CSV has empty fields for forward_lean, posture_good
         
Frame 3: YOLO detects 14 keypoints, but left ear not visible
         → posture_good=None (can't compute head angle without both ears)
```

---

### Step 3: YOLOv8n → Phone Detection (EVERY frame)

**What it does:**
- Standard YOLO object detection looking for COCO class 67 ("cell phone")
- Scans the entire frame for phones

**Returns:**
- `phone_detected`: True/False
- `bounding_boxes`: list of detected phone locations (not used in state machine, just for visualization)

**Real example:**

```
Frame 1: No phone in frame
         → phone_detected=False
         
Frame 2: Phone visible on desk
         → phone_detected=True
         → State machine immediately switches to PHONE state (no delay)
```

---

### Step 4: MoViNet-A2-Stream → Action Recognition (EVERY 5th frame)

**What it is:**
- MoViNet is a **streaming video model** that remembers previous frames
- Uses RNN/LSTM-like internal states to carry temporal context
- Trained on YouTube videos of people studying, sleeping, and other activities

**What it does:**

1. **Input:** Current frame resized to 172×172 pixels
2. **Processing:** Passes through MoViNet-A2 model (runs on CPU, ~93ms)
3. **Output:** Softmax probabilities over 3 classes:
   - `studying`: probability person is studying (0.0 to 1.0)
   - `sleeping`: probability person is sleeping (0.0 to 1.0)
   - `other`: probability person is doing something else (0.0 to 1.0)
   - (These three sum to 1.0)

4. **EMA Smoothing:** Applies exponential moving average with decay=0.9
   - Smooths out jitter and noise in predictions
   - Formula: `smoothed_conf = 0.9 × old_conf + 0.1 × new_conf`
   - Makes predictions more stable

5. **Confidence threshold:** If max confidence < 0.4 → defaults to "other"
   - Prevents low-confidence predictions from affecting state machine

**Between MoViNet calls:**
- MoViNet only runs every 5 frames (~93ms per call)
- Frames 1-4: Last prediction is reused (same confidence)
- Frame 5: MoViNet runs, new prediction computed
- Frames 6-9: Reuse frame 5's prediction
- Frame 10: MoViNet runs again

**Real example:**

```
Frame 1: MoViNet runs
         → studying=0.78, sleeping=0.05, other=0.17
         → max=studying, conf=0.78 (> 0.4, so use it)
         → action=studying, confidence=0.78
         
Frame 2-4: Reuse frame 1's prediction
         → action=studying, confidence=0.78 (same)
         
Frame 5: MoViNet runs again
         → studying=0.45, sleeping=0.08, other=0.47
         → max=other, conf=0.47
         → EMA smooth: 0.9 × 0.78 + 0.1 × 0.47 = 0.75
         → action=other, confidence=0.75
         
Frame 6-9: Reuse frame 5's prediction
         → action=other, confidence=0.75 (same)
```

---

### Step 5: State Machine → State Decision (EVERY frame)

**What it does:**
- Takes inputs from MoViNet, posture detection, phone detection, and person detection
- Applies a **priority system** and **debouncing** to decide what state to display

**Priority system (highest priority wins):**

```
Priority 1: AWAY
  Trigger: No person detected for 3 seconds (90 frames)
  Action: Display "AWAY"
  
Priority 2: PHONE
  Trigger: phone_detected=True
  Action: Display "PHONE" IMMEDIATELY (no delay)
  
Priority 3: SLEEPING
  Trigger: action=sleeping for 3 consecutive frames
  Action: Display "SLEEPING"
  
Priority 4: SLOUCHING
  Trigger: posture_good=False for 30 consecutive frames (~1 second)
  Action: Display "SLOUCHING"
  
Priority 5: DISTRACTED
  Trigger: action=other for 8 seconds (240 frames)
  Action: Display "DISTRACTED"
  
Priority 6: STUDYING
  Trigger: action=studying for 3 consecutive frames
  Action: Display "STUDYING"
```

**Debouncing (prevents flickering):**

- **Enter STUDYING:** Need 3 consecutive frames of action=studying
  - Prevents brief "studying" predictions from changing state
  
- **Exit STUDYING:** Need 5 consecutive frames of NOT studying
  - Prevents brief interruptions from changing state
  - This is why you see STUDYING persist even when MoViNet briefly says "other"

**Real example:**

```
Frame 1: action=studying, posture_good=True, phone_detected=False
         → Need 3 frames of studying to enter STUDYING state
         → state=STUDYING (if already in it)
         
Frame 2: action=studying, posture_good=True, phone_detected=False
         → state=STUDYING
         
Frame 3: action=other, posture_good=True, phone_detected=False
         → action changed to "other", but need 5 frames to exit
         → state=STUDYING (still, debouncing)
         
Frame 4: action=other, posture_good=True, phone_detected=False
         → state=STUDYING (2/5 frames of "other")
         
Frame 5: action=other, posture_good=True, phone_detected=False
         → state=STUDYING (3/5 frames of "other")
         
Frame 6: action=other, posture_good=True, phone_detected=False
         → state=STUDYING (4/5 frames of "other")
         
Frame 7: action=other, posture_good=True, phone_detected=False
         → state=DISTRACTED (5/5 frames of "other", exit STUDYING)
         
Frame 8: action=studying, posture_good=True, phone_detected=False
         → action changed back to studying, but need 3 frames to re-enter
         → state=DISTRACTED (debouncing, reset counter)
         
Frame 9: action=studying, posture_good=True, phone_detected=False
         → state=DISTRACTED (1/3 frames of studying)
         
Frame 10: action=studying, posture_good=True, phone_detected=False
          → state=DISTRACTED (2/3 frames of studying)
          
Frame 11: action=studying, posture_good=True, phone_detected=False
          → state=STUDYING (3/3 frames of studying, re-enter)
```

---

### Step 6: Engagement Engine → Focus Score (EVERY frame)

**What it does:**
- Computes a single "focus score" (0-100%) that represents overall engagement
- Combines posture, action confidence, and phone detection into one metric

**Formula:**

```
frame_score = 0.30 × posture_score
            + 0.40 × studying_confidence
            + 0.30 × no_phone_score

where:
  posture_score = 1.0 if posture_good=True, else 0.0
  studying_confidence = MoViNet confidence (0.0 to 1.0)
  no_phone_score = 1.0 if phone_detected=False, else 0.0
```

**Example calculation:**

```
Frame 1: posture_good=True, studying_conf=0.82, phone_detected=False
         frame_score = 0.30 × 1.0 + 0.40 × 0.82 + 0.30 × 1.0
                     = 0.30 + 0.328 + 0.30
                     = 0.928 (92.8%)
         
Frame 2: posture_good=False, studying_conf=0.82, phone_detected=False
         frame_score = 0.30 × 0.0 + 0.40 × 0.82 + 0.30 × 1.0
                     = 0.0 + 0.328 + 0.30
                     = 0.628 (62.8%)
         
Frame 3: posture_good=True, studying_conf=0.35, phone_detected=True
         frame_score = 0.30 × 1.0 + 0.40 × 0.35 + 0.30 × 0.0
                     = 0.30 + 0.14 + 0.0
                     = 0.44 (44%)
```

**Hysteresis (prevents jitter):**
- Applies 0.85-second hysteresis before changing displayed score
- Prevents the focus_score from jumping around too much
- Updates rolling average for the displayed focus_score percentage

**Special case:**
- If calibration is in progress → focus_score = 0.0 (system doesn't score until calibration completes)

---

### Step 7: Calibration System

**What it does:**
- Establishes a **personal baseline** of your posture while sitting still
- Creates personalized thresholds for "good posture" vs "slouching"
- Monitors for position changes and triggers recalibration if you move

**States:**

```
WAITING
  ↓ (good posture for 1.5 seconds)
CALIBRATING
  ↓ (collect 30+ samples in ~10 seconds)
ACTIVE
  ↓ (monitors for position change)
  ├─ (position change detected for 15 frames)
  └─→ RECALIBRATING
       ↓ (collect 30+ samples)
       └─→ ACTIVE
```

**WAITING state:**
- System is idle, waiting for you to sit still
- Checks if posture_good=True for 1.5 seconds continuously
- If you slouch or move → resets timer

**CALIBRATING state:**
- Collects posture samples while you sit still with good posture
- Needs at least 30 accepted samples within ~10 seconds
- Each frame with posture_good=True is a candidate sample
- Quality checks:
  - Posture must be good (forward_lean < threshold, etc.)
  - Neck angle must be forward-facing (not turned)
  - Back angle must be reasonable
  - No extreme slouching

**What calibration computes:**

For each angle (forward_lean, neck_angle, back_angle):

1. **Median:** Your personal baseline angle
   - Example: Your median forward_lean = 6.2°

2. **MAD (Median Absolute Deviation):** Your personal variation
   - Example: Your MAD forward_lean = 2.1°

3. **Personalized threshold:**
   ```
   threshold = median + 2.5 × max(MAD, min_variation)
   
   where min_variation = 3.0° for forward_lean, 5.0° for neck_angle
   ```
   - Example: forward_lean_threshold = 6.2 + 2.5 × max(2.1, 3.0)
                                     = 6.2 + 2.5 × 3.0
                                     = 6.2 + 7.5
                                     = 13.7°
   - So anything > 13.7° is considered slouching for you

**ACTIVE state:**
- Baseline established, system is monitoring
- Checks if your shoulder midpoint (pose_centroid) has moved significantly
- Position change detection:
  - If x_change > 5% of frame width OR y_change > 8% of frame height
  - For 15 consecutive frames → triggers RECALIBRATING
  - Resets counter if you stay still for even one frame

**RECALIBRATING state:**
- Same as CALIBRATING, but you've already moved
- Re-establishes baseline with new position
- After 30+ samples → returns to ACTIVE

**Real example:**

```
Frame 1-50: WAITING
            You're moving around, posture_good=False
            
Frame 51: You sit down with good posture
          posture_good=True
          Timer starts: 0.0s
          
Frame 52-100: WAITING
              You stay still, posture_good=True
              Timer: 0.0s → 1.5s
              
Frame 101: Timer reaches 1.5s
           [CAL] Good posture detected for 1.5s, starting calibration!
           state=CALIBRATING
           
Frame 102-200: CALIBRATING
               Collecting samples
               [CAL DEBUG] 5.3s | frames=99 pose_ok=99(100%) called=20 accepted=28
               
Frame 201: 30 samples collected
           [CAL FINALIZE] samples=32/30 elapsed=10.0s rate=3.2/s
           ✓ Calibration complete!
           state=ACTIVE
           
Frame 202-500: ACTIVE
               Monitoring for position change
               
Frame 501: You lean back slightly
           [CAL POS] x_change=0.0012 y_change=0.0342 consecutive=1/15
           
Frame 502-515: ACTIVE
               Position change continues
               [CAL POS] x_change=0.0823 y_change=0.0956 consecutive=15/15
               
Frame 516: 15 consecutive frames of movement
           ⚠ Position change detected, recalibrating...
           state=RECALIBRATING
           
Frame 517-600: RECALIBRATING
               Collecting new baseline
               
Frame 601: 30 samples collected
           state=ACTIVE
```

---

### Step 8: Dashboard Rendering

**What it does:**
- Overlays all the computed information on the video frame
- Displays skeleton, status text, action label, confidence, focus score

**Visual elements:**

1. **Skeleton:** Green lines connecting detected keypoints
   - Shows YOLO's pose detection
   - If skeleton is missing → YOLO couldn't detect pose

2. **Status text:** Top-left corner
   - "STUDYING", "SLEEPING", "SLOUCHING", "DISTRACTED", "PHONE", "AWAY"
   - Color: GREEN = studying, YELLOW = warning, RED = distracted

3. **Action label:** Top-right corner
   - Shows MoViNet's raw prediction: "studying", "sleeping", "other"
   - Shows confidence: "studying (0.82)"

4. **Focus score:** Bottom-right corner
   - "Focus: 87.3%"
   - Updates every frame

5. **Calibration status:** Bottom-left corner
   - "WAITING", "CALIBRATING", "ACTIVE"
   - Shows progress during calibration

---

## Part 4: Debugging Tips — Common Patterns to Look For

### "Why does it say NOT STUDYING when I'm studying?"

**Check these in order:**

1. **Look at the `source` column in CSV:**
   - If `source=other` → MoViNet doesn't recognize your activity as studying
   - This is a **domain gap issue** (model trained on YouTube videos, not webcam footage)
   - Solution: Try different camera angles, better lighting, or different activities

2. **Look at the `studying` column (confidence):**
   - If < 0.4 → MoViNet is very uncertain
   - Check if you're doing something unusual (not typical studying)
   - Solution: Sit at a desk, look at a screen, take notes

3. **Check the state machine debouncing:**
   - If `source=studying` but `state=DISTRACTED` → need 3 frames of studying to re-enter
   - Look at the CSV: how many consecutive "studying" frames do you have?
   - Solution: Keep studying for 3+ frames (0.3 seconds)

---

### "Why does it keep saying SLOUCHING?"

**Check these in order:**

1. **Look at the `forward_lean` column:**
   - If > 11-15° → your head is forward of your shoulders
   - This is the main slouching indicator
   - Solution: Sit back, keep head above shoulders

2. **Check if `posture_good` is empty:**
   - Empty = YOLO couldn't detect your keypoints
   - Causes: poor lighting, camera angle too high/low, face partially hidden
   - Solution: Improve lighting, adjust camera to eye level, clear your face

3. **Check the calibration baseline:**
   - Look at [CAL FINALIZE] line for your baseline
   - If your baseline forward_lean is high (> 10°) → you slouched during calibration
   - Solution: Sit with good posture during calibration, then recalibrate

4. **Check the personalized threshold:**
   - Your threshold = your_median + 2.5 × your_variation
   - If threshold is low (< 10°) → system is sensitive to slouching
   - This is correct if you have very stable posture
   - Solution: Sit still during calibration to establish a good baseline

---

### "Why does it recalibrate randomly?"

**Check these in order:**

1. **Look at the `[CAL POS]` lines:**
   - Are `x_change` or `y_change` values high?
   - If yes → you're moving, triggering recalibration
   - Solution: Sit still, don't shift your position

2. **Check if you were slouching/sleeping:**
   - If you slouch, your shoulder midpoint moves (known issue)
   - If you sleep, your head drops, shoulder midpoint moves
   - Solution: Maintain good posture, don't sleep

3. **Check the consecutive counter:**
   - Did it reach 15/15?
   - If yes → 15 consecutive frames of movement triggered recalibration
   - Solution: Sit still for 15+ frames (1.5 seconds)

4. **Check if YOLO lost pose detection:**
   - If `[CAL POS]` lines disappear → YOLO can't detect pose
   - Solution: Improve lighting, adjust camera angle

---

### "Why is focus_score stuck at 0.0?"

**This means calibration is in progress.**

- Check the `state` column: is it "CALIBRATING" or "RECALIBRATING"?
- If yes → system doesn't score until calibration completes
- Solution: Sit still with good posture for ~10 seconds to complete calibration

---

### "Why are there empty fields in the CSV?"

**Empty fields mean YOLO-pose couldn't detect enough keypoints that frame.**

Common causes:
- Hand covering face
- Turned sideways (ears not visible)
- Poor lighting
- Moving too fast
- Camera angle too high/low

Solution:
- Improve lighting
- Adjust camera to eye level
- Keep face visible and forward-facing
- Sit still

---

### "Why is the skeleton (pose overlay) missing?"

**YOLO couldn't detect pose that frame.**

- Check `person_present` column: is it True?
- If False → YOLO didn't detect a person at all
- If True → YOLO detected person but couldn't extract pose

Solutions:
- Improve lighting
- Adjust camera angle (should be at eye level)
- Make sure your full body is visible
- Sit still (moving too fast confuses YOLO)

---

### "Why does the phone detection trigger randomly?"

**YOLOv8n is detecting something as a phone that isn't.**

- Check the `phone_detected` column: is it True when you don't have a phone?
- This is a **false positive** in phone detection
- Solution: Adjust camera angle, remove objects that look like phones

---

### "Why are MoViNet predictions inconsistent?"

**MoViNet is a neural network, not a rule-based system. It can be uncertain.**

- Check the `studying` column (confidence): is it close to 0.5?
- If yes → MoViNet is genuinely uncertain about what you're doing
- This is normal and expected
- Solution: Sit at a desk, look at a screen, take notes (clearer studying signal)

---

## Summary: Quick Reference

**Terminal logs tell you:**
- `[ML]` lines: What MoViNet predicted and what state machine decided
- `[CAL POS]` lines: Whether you're moving (position change detection)
- `[CAL DEBUG]` lines: Calibration progress and sample quality
- `[CAL FINALIZE]` lines: Calibration completion
- `[CAL]` status lines: Calibration state changes
- `[MOVINET]` lines: MoViNet internal events (rare)
- `[DEBUG]` lines: CSV logging started/stopped

**CSV columns tell you:**
- `state`: What's displayed on screen (the final verdict)
- `source`: MoViNet's raw prediction
- `studying`: MoViNet's confidence (0.0-1.0)
- `forward_lean`: How far your head is forward (degrees)
- `posture_good`: Is your posture acceptable? (True/False/empty)
- `phone_detected`: Is a phone visible? (True/False)
- `focus_score`: Overall engagement (0-100%)

**The pipeline:**
1. Camera captures frame (1280×720)
2. YOLOv8-Pose detects posture (every frame)
3. YOLOv8n detects phone (every frame)
4. MoViNet predicts action (every 5th frame)
5. State machine decides state (every frame, with debouncing)
6. Engagement engine computes focus score (every frame)
7. Calibration system monitors position (every frame)
8. Dashboard renders everything (every frame)

**When debugging:**
1. Check the terminal logs for state changes
2. Open the CSV file and look at the columns
3. Trace through the pipeline: posture → MoViNet → state machine → focus score
4. Check calibration status: is it WAITING, CALIBRATING, or ACTIVE?
5. Look for patterns: are certain columns consistently empty? Are values extreme?

---

**Last updated:** February 2026
**System version:** KID-WATCH v0.3 (ML detector mode)
**Model versions:** MoViNet-A2-Stream, YOLOv8n-Pose, YOLOv8n
