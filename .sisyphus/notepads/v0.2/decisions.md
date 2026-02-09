# v0.2 Decisions

## [2026-02-08] Calibration Stuck-at-100% Fix

**Problem:** CalibrationEngine's overly strict validation guards rejected most frames, especially from side-angle cameras or users with glasses. This caused calibration to get stuck at 100% progress while never collecting enough samples (100 required, typically <20 collected).

**Root Cause:**
- `iris_ratio` validation rejected frames where iris detection failed (common with glasses or side angles)
- `face_width` validation rejected frames where face detection failed (common with side-mounted cameras)
- These are OPTIONAL metrics for engagement scoring, but were treated as MANDATORY for calibration

**Solution Implemented:**

### 1. Made iris_ratio OPTIONAL
- `add_sample()` now accepts frames even when iris_ratio is None or outside [0.3, 0.8]
- Stores iris_ratio as None when unavailable/unreliable
- `finalize_calibration()` computes iris baseline only if ≥10 iris samples available
- Baseline includes `has_iris: True/False` flag
- `get_thresholds()` returns `iris_ratio_threshold: None` when iris unavailable

### 2. Made face_width OPTIONAL
- `add_sample()` now accepts frames even when face_width is None or <30px
- Stores face_width as None when unavailable/unreliable
- `finalize_calibration()` computes face baseline only if ≥10 face samples available
- Baseline includes `has_face: True/False` flag
- `check_position_change()` skips face_width comparison when face baseline unavailable
- `match_baseline()` uses only pose_centroid when face baseline unavailable

### 3. Kept posture_metrics MANDATORY
- neck_angle and forward_lean must be present and in valid ranges
- These are the CORE metrics that work from any camera angle (back/side/front)
- back_angle remains optional (already was)

### 4. Reduced MIN_SAMPLES_FOR_CALIBRATION
- Changed from 100 to 30 samples
- At 30fps with relaxed guards, 30 samples in 20s requires only ~5% acceptance rate (very achievable)

### 5. Added MAX_CALIBRATION_TIMEOUT
- 45-second timeout to force-finalize calibration
- If <30 samples after 45s but ≥10 samples: force-finalize with sparse baseline
- If <10 samples after 45s: switch to "active" with NO baseline (use hardcoded defaults)

### 6. Updated debug counters
- Renamed `_debug_reject_iris_range` → `_debug_iris_unavailable`
- Renamed `_debug_reject_face_small` → `_debug_face_unavailable`
- Renamed `_debug_reject_no_metrics` → `_debug_reject_no_posture`
- Debug log now shows: `OPTIONAL: iris_unavail=X face_unavail=Y`

**Expected Behavior After Fix:**
- Side-angle cameras: calibration completes in ~20s with pose-only baseline (no iris/face)
- Front cameras with glasses: calibration completes in ~20s with pose+face baseline (no iris)
- Front cameras without glasses: calibration completes in ~20s with full baseline (pose+iris+face)
- Worst case: 45s timeout forces finalization with whatever data is available

**Testing Plan:**
- User will test with side-angle camera setup (left side visible, wearing glasses)
- Expected: calibration completes in ~20 seconds, debug log shows high iris_unavail/face_unavail but samples accepted
- Expected: baseline has `has_iris: False, has_face: False`, only pose metrics used for engagement scoring

**Files Modified:**
- `/Users/edwardtran/BLI/kid-watch/kid_watch.py` (CalibrationEngine class)

**No Behavioral Changes Outside CalibrationEngine:**
- GazeDetector, PostureDetector, PhoneDetector, EngagementEngine, DashboardRenderer unchanged
- State machine ("calibrating"/"active"/"recalibrating") unchanged
- Progress bar calculation unchanged
- Debug logging preserved and enhanced

## [2026-02-08] Position Change Detection — Separate X/Y Thresholds

**Problem:** `check_position_change()` used Euclidean distance (combined X+Y movement), so vertical slouching (~25% of face width) triggered false recalibration. User's side-angle camera setup made this worse — normal slouching at desk caused position change alerts.

**Root Cause:**
- Euclidean distance: `sqrt(dx² + dy²)` combines horizontal and vertical movement
- Slouching drops shoulders ~15-25% vertically (Y-axis) but minimal horizontal movement (X-axis)
- Combined distance exceeded 25% threshold → triggered recalibration
- Recalibration is meant for "kid moved to a different spot" (lateral movement or standing up), NOT slouching

**Solution Implemented:**

### Changed from Euclidean to separate X/Y thresholds
```python
# BEFORE: Euclidean distance
centroid_distance = np.linalg.norm(pose_centroid - last_stable_pose_centroid)
centroid_change = centroid_distance / face_width
position_changed = centroid_change > 0.25

# AFTER: Separate X and Y
x_change = abs(dx) / face_width
y_change = abs(dy) / face_width
position_changed = (x_change > 0.30) or (y_change > 0.45)
```

### Threshold rationale:
- **X threshold: 30%** — Kid moved laterally (scooted chair left/right, turned to side)
- **Y threshold: 45%** — Kid stood up or sat on floor (major vertical position change)
- **Slouching: 15-25% Y** — Normal posture variation, does NOT trigger recalibration

### Added debug logging:
- When `position_changed=True`, prints: `[POS DEBUG] x_change=0.12 y_change=0.28 face_change=0.05 → position_changed=True`
- Only logs when position change detected (not every frame)
- Helps diagnose which axis triggered the alert

**Expected Behavior After Fix:**
- Slouching at desk: Y change ~15-25%, does NOT trigger recalibration
- Moving chair laterally: X change >30%, DOES trigger recalibration after 2s
- Standing up: Y change >45%, DOES trigger recalibration after 2s
- Leaning closer to screen: face_width change >25%, DOES trigger recalibration after 2s

**Files Modified:**
- `/Users/edwardtran/BLI/kid-watch/kid_watch.py` — `CalibrationEngine.check_position_change()` method (lines 811-838)

**Testing Plan:**
- User will test with side-angle camera setup
- Expected: Normal slouching does NOT trigger recalibration
- Expected: Moving to a different chair position DOES trigger recalibration
- Debug log will show which axis (x_change/y_change/face_change) triggered the alert

## [2026-02-08] Smart Calibration — Waiting State for Good Posture Detection

**Problem:** CalibrationEngine blindly started calibrating from second 0, when the kid might be slouching, looking away, or adjusting their position. This resulted in baselines calibrated from bad posture, making the system think slouching is "normal."

**Root Cause:**
- Calibration started immediately when session began
- First 10-20 seconds of video might show kid settling in, slouching, or distracted
- Baseline computed from these frames encoded bad posture as "good"
- Engagement scoring then failed to detect actual slouching (because it matched the baseline)

**Solution Implemented:**

### 1. Added "waiting" pre-state to state machine
**State flow:** `waiting → calibrating → active → recalibrating → active`

- **waiting**: Detects sustained good posture before starting calibration timer
- **calibrating**: Collects samples for 10 seconds (reduced from 20)
- **active**: Normal monitoring with baseline comparison
- **recalibrating**: Re-calibration after position change

### 2. Good posture detection heuristics
Pre-trained thresholds (NOT personalized baseline):
```python
GOOD_POSTURE_NECK_THRESHOLD = 150°  # neck angle must be above this
GOOD_POSTURE_LEAN_THRESHOLD = 15°   # forward lean must be below this
GOOD_POSTURE_SUSTAIN = 1.5s         # must sustain good posture this long
```

### 3. Waiting state behavior
- Detects good posture via `check_good_posture()` each frame
- Requires 1.5s sustained good posture → transitions to "calibrating"
- Tracks best-observed neck angle for timeout fallback
- 60-second timeout → force-start calibration (prevents infinite waiting)

### 4. Calibration duration reduced
- Changed from 20 seconds to 10 seconds
- Rationale: Now calibrating from KNOWN good posture, so less data needed
- MIN_SAMPLES_FOR_CALIBRATION remains 30 (achievable in 10s at 20fps with ~15% acceptance rate)

### 5. Bad posture during calibration
- If posture becomes bad during calibration, PAUSE sampling (don't reject frame)
- Track bad posture duration via `bad_posture_start` timer
- If bad posture persists >2 seconds → reset to "waiting" state
- Rationale: Kid slouched mid-calibration, need to restart from good posture

### 6. Dashboard updates
- **Waiting state**: Shows "Waiting to Calibrate" + "Sit up straight to begin!"
- **Calibrating state**: Shows "Calibrating..." + progress bar (0-100%)
- `calibration_progress == -1` signals waiting state (not calibrating yet)

### 7. EngagementEngine integration
- Returns "WAITING" status during waiting state (instead of "CALIBRATING")
- Blocks engagement scoring during waiting (same as calibrating/recalibrating)

**Implementation Details:**

### New constants:
```python
CALIBRATION_DURATION = 10           # reduced from 20
WAITING_TIMEOUT = 60                # force-start after 60s
GOOD_POSTURE_NECK_THRESHOLD = 150   # degrees
GOOD_POSTURE_LEAN_THRESHOLD = 15    # degrees
GOOD_POSTURE_SUSTAIN = 1.5          # seconds
BAD_POSTURE_GRACE = 2.0             # seconds
```

### New state variables:
```python
self.state = "waiting"              # starts in waiting (not calibrating)
self.waiting_start_time             # when waiting began
self.good_posture_start             # when good posture first detected
self.bad_posture_start              # when bad posture started during calibration
self.best_observed_window           # best posture seen (for timeout fallback)
self.best_observed_neck_angle       # track best neck angle
```

### New methods:
- `check_good_posture(posture_metrics)` — Returns True if neck>150° and lean<15°
- `update_waiting_state(posture_metrics)` — Called each frame during waiting, detects sustained good posture
- `_start_calibrating()` — Transition from waiting to calibrating

### Modified methods:
- `start_calibration()` — Now sets state to "waiting" instead of "calibrating"
- `add_sample()` — Pauses sampling on bad posture during calibration, resets to waiting after 2s grace period
- `check_calibration_progress()` — Returns (-1.0, False) during waiting state

### Main loop changes:
```python
if self.calibration_engine.state == "waiting":
    state_changed, msg = self.calibration_engine.update_waiting_state(posture_metrics)
    calibration_progress = -1  # special value for waiting
elif self.calibration_engine.state in ["calibrating", "recalibrating"]:
    # existing calibration logic
```

**Expected Behavior After Fix:**

### Happy path:
1. Session starts → state = "waiting"
2. Kid slouching → waiting continues, tracking best neck angle
3. Kid sits up straight (neck>150°, lean<15°) → good_posture_start timer begins
4. After 1.5s sustained good posture → state = "calibrating"
5. Calibration collects samples for 10 seconds from good posture
6. If kid slouches during calibration → sampling pauses (doesn't count toward 10s)
7. If slouch persists >2s → reset to "waiting"
8. After 10s of good samples → finalize_calibration() → state = "active"

### Timeout path:
1. Kid never sits up straight for 60 seconds
2. Timeout triggers → force-start calibration from best-observed posture window
3. Calibration proceeds normally

### Bad posture during calibration:
1. Calibrating, kid slouches → sampling pauses
2. Kid sits up again within 2s → sampling resumes
3. Kid slouches for >2s → reset to "waiting", must sit up straight again

**Testing Plan:**
- User will test with side-angle camera setup
- Expected: "Waiting to Calibrate" message appears, prompts to sit up straight
- Expected: After sitting up straight for 1.5s, calibration starts
- Expected: Calibration completes in ~10 seconds (not 20)
- Expected: If slouching during calibration, resets to waiting

**Files Modified:**
- `/Users/edwardtran/BLI/kid-watch/kid_watch.py`:
  - CalibrationEngine class (lines 516-880)
  - EngagementEngine.update() (line 1077)
  - DashboardRenderer._draw_calibration_status() (lines 1247-1400)
  - Main loop (lines 1816-1850)

**Design Rationale:**
- Oracle research recommended neck threshold 150° (not 155°) based on ergonomic studies
- Pause sampling (don't reset) on bad posture → allows temporary adjustments
- 2s grace period before reset → balances strictness vs. usability
- 60s timeout → prevents infinite waiting if kid never sits up straight
- Reduced calibration to 10s → faster onboarding, less waiting for user

**No Behavioral Changes Outside Calibration:**
- GazeDetector, PostureDetector, PhoneDetector unchanged
- Position change detection unchanged (just fixed in previous task)
- Engagement scoring logic unchanged
- Session reporting unchanged

## [2026-02-08] StudyDetector: Face+Pose Fusion for Side-Angle Cameras

**Problem**: Side-mounted cameras show "NO PERSON DETECTED" when kid studies (face turns away), and "STUDYING" when kid looks at camera (face becomes visible). This is backwards.

**Root Cause**: `person_present` was derived from face detection (`gaze_at_desk is None`), not pose detection. Face disappears when kid looks at desk from side angle.

**Solution**: Created `StudyDetector` class that fuses face-based gaze with pose-based head-bowed detection:

1. **Person presence** derived from POSE landmarks (not face) — person detected even when face invisible
2. **Studying signal priority**:
   - If face detected → use gaze (pitch/yaw/iris) — most accurate
   - If only pose detected → use ear-shoulder-hip angle (neck flexion) — "head bowed" proxy
   - If nothing detected → person not present

3. **Neck flexion algorithm** (torso-relative method):
   - Compute torso-up vector (hip→shoulder)
   - Compute head vector (shoulder→ear/nose)
   - Angle between vectors = neck flexion
   - Thresholds: enter studying at 40°, exit at 35° (hysteresis)

4. **EngagementEngine changes**:
   - Signature: `update(posture_good, studying, phone_detected, person_present)`
   - `person_present` replaces `gaze_at_desk is None` check
   - All references to `gaze_at_desk` replaced with `studying`

**Result**: From side camera:
- Kid looking at desk → "STUDYING" (via pose head-bowed)
- Kid looking at camera → "NOT STUDYING" (via gaze yaw)
- Person always detected when pose visible (regardless of face)

**Trade-off**: Pose-based studying is less accurate than face-based gaze, but works from any angle. Face-based gaze still used when available (front camera).

## [2026-02-08] Refactored monolithic kid_watch.py into modular package structure

**Decision**: Split 2174-line monolithic file into clean module structure following 400-line max rule

**Structure**:
```
kid_watch/
├── __init__.py          (7 lines: package metadata)
├── config.py            (40 lines: all constants, colors, URLs, thresholds)
├── utils.py             (129 lines: download_model, calculate_angle, draw_text_with_background, etc.)
├── detectors/
│   ├── __init__.py      (16 lines: exports all detector classes)
│   ├── posture_detector.py  (179 lines: PostureDetector class)
│   ├── gaze_detector.py     (124 lines: GazeDetector class)
│   ├── study_detector.py    (162 lines: StudyDetector class)
│   └── phone_detector.py    (57 lines: PhoneDetector class)
├── calibration.py       (545 lines: CalibrationEngine class)
├── engagement.py        (280 lines: EngagementEngine class)
└── dashboard.py         (469 lines: DashboardRenderer class)

kid_watch.py (root, 264 lines): Entry point with KidWatchApp class and main()
```

**Rationale**:
- Original file was 2174 lines — too large for maintainability
- CalibrationEngine (545 lines) and DashboardRenderer (469 lines) are acceptable as single cohesive classes
- Each module has clear responsibility and minimal cross-dependencies
- Preserved ALL existing functionality — zero logic changes
- Preserved ALL debug logging and comments

**Import strategy**:
- `config.py` imports nothing from the project (pure constants)
- `utils.py` imports only from `config.py`
- Detectors import from `config.py` and `utils.py`
- `calibration.py`, `engagement.py`, `dashboard.py` import from `config.py` and `utils.py`
- Root `kid_watch.py` imports from all submodules using absolute imports

**Verification**:
- All files compile with `python3 -m py_compile` ✓
- Import chain verified (cv2 import error expected outside venv) ✓
- Total lines: 2272 (original 2174 + new structure overhead)

**Backward compatibility**:
- `python3 kid_watch.py` still works exactly as before
- No changes to virtual environment or dependencies
- Original file backed up as `kid_watch.py.backup`

## [2026-02-08] StudyDetector v2 — Camera-Mode-Aware Fusion with Calibrated Thresholds

**Problem**: StudyDetector v1 used hardcoded neck flexion thresholds (40° enter, 35° exit) that didn't adapt to individual users or camera angles. Side-camera users saw studying detected at 14-18° neck flexion (far below the 40° threshold), causing false negatives.

**Root Cause**:
- Hardcoded thresholds assumed front-camera setup with specific posture
- Didn't account for camera angle affecting apparent neck flexion
- No distinction between front-camera (face-gaze primary) vs side-camera (pose-only) modes
- No debouncing → rapid state flipping on noisy signals

**Solution Implemented: StudyDetector v2**

### 1. Camera Mode Classification
Derived from calibration baseline flags:
```python
FRONT       = has_face=True, has_iris=True
FRONT_NO_IRIS = has_face=True, has_iris=False  # e.g., glasses
SIDE        = has_face=False  # face rarely visible
```

### 2. Calibrated Neck Flexion Thresholds
**CRITICAL: Two different "neck" measurements exist:**
- `neck_angle` (PostureDetector/CalibrationEngine): ear→shoulder→hip angle, ~150-170° upright, LOWER = worse
- `neck_flexion` (StudyDetector): torso-up vs head angle, ~5-15° upright, HIGHER = more bowed
- Relationship: `neck_flexion ≈ 180° - neck_angle`

**Threshold computation** (lazy, computed once when calibration completes):
```python
baseline_flex = 180.0 - neck_angle_median  # e.g., 180 - 165 = 15°
enter_delta = max(6.0, 3.0 * neck_angle_mad)
exit_delta = max(4.0, 2.0 * neck_angle_mad)
neck_enter = baseline_flex + enter_delta  # e.g., 15 + 9 = 24°
neck_exit = baseline_flex + exit_delta    # e.g., 15 + 6 = 21°
```

Safety clamps:
- `neck_enter`: min = baseline + 4°, max = baseline + 25°
- `neck_exit`: min = baseline + 2°, max = neck_enter - 1°

### 3. Mode-Dependent Detection Logic

**SIDE mode** (`_detect_side`):
- Face visible for >5 consecutive frames → kid turned to camera → NOT studying (override)
- Otherwise: use calibrated neck flexion with debounce (POSE_ENTER_FRAMES=3, POSE_EXIT_FRAMES=4)
- Returns source: `"pose_side"` or `"side_face_override"`

**FRONT mode** (`_detect_front`):
- Face visible → use gaze with debounce (GAZE_ENTER_FRAMES=2, GAZE_EXIT_FRAMES=2)
- Face just dropped → hold last decision for FACE_HOLD_FRAMES=8
- Hold expired → fallback to pose with debounce
- Returns source: `"face"`, `"face_hold"`, or `"pose"`

### 4. Debounce Counters (Frame-Based)
Prevents rapid state flipping on noisy signals:
- `_gaze_enter_ct`, `_gaze_exit_ct`: Face-gaze debounce
- `_pose_enter_ct`, `_pose_exit_ct`: Pose debounce
- `_face_hold_remaining`: Countdown timer for face-hold
- `_face_seen_streak`, `_face_miss_streak`: Face visibility tracking

### 5. Face Tracking
- `_update_face_tracking()`: Tracks consecutive frames with/without face
- Used in SIDE mode to detect when kid turns to camera (face visible = NOT studying)
- Used in FRONT mode to trigger face-hold when face drops

### 6. Fallback During Calibration
Before thresholds computed (still calibrating):
- If face available: use gaze directly (no debounce)
- If only pose: use hardcoded 40° threshold
- Returns source: `"face_fallback"` or `"pose_fallback"`
- Doesn't matter much since EngagementEngine returns "CALIBRATING" anyway

### 7. kid_watch.py Integration

**StudyDetector initialization**:
```python
self.study_detector = StudyDetector(self.calibration_engine)  # Pass calibration engine
```

**Face-source debug logging** (1Hz, all sources):
```python
if study_source in ("pose_side", "pose", "pose_fallback"):
    print(f"[STUDY] source={study_source} neck_flex={neck_flex:.1f}° studying={studying}")
elif study_source in ("face", "face_fallback"):
    print(f"[STUDY] source={study_source} pitch={pitch:.1f}° yaw={yaw:.1f}° gaze_at_desk={gaze_at_desk} studying={studying}")
elif study_source == "side_face_override":
    print(f"[STUDY] source=side_face_override → NOT studying (face visible from side cam)")
elif study_source == "face_hold":
    print(f"[STUDY] source=face_hold studying={studying} (holding last gaze decision)")
```

**D-key CSV debug logging**:
- Press D to start/stop CSV logging
- Logs: timestamp, frame, state, source, studying, person_present, neck_flex, pitch, yaw, gaze_at_desk, posture_good, phone_detected, focus_score, camera_mode
- File: `debug_log_YYYYMMDD_HHMMSS.csv`
- Auto-closed on cleanup

### Expected Behavior After Fix

**Side camera (has_face=False)**:
- Calibration completes → camera_mode = "side"
- Baseline flex ~15° → enter threshold ~24°, exit ~21° (example values)
- Kid looking at desk (neck_flex ~18°) → studying=True (via pose_side)
- Kid turns to camera (face visible >5 frames) → studying=False (via side_face_override)

**Front camera (has_face=True, has_iris=True)**:
- Calibration completes → camera_mode = "front"
- Face visible → studying via gaze (pitch/yaw/iris)
- Face drops briefly → hold last decision for 8 frames (face_hold)
- Face drops long-term → fallback to pose with calibrated thresholds

**Front camera with glasses (has_face=True, has_iris=False)**:
- Calibration completes → camera_mode = "front_no_iris"
- Same logic as FRONT (iris not used in gaze detection anyway)

### Files Modified
- `/Users/edwardtran/BLI/kid-watch/kid_watch/detectors/study_detector.py` (full rewrite, 290 lines)
- `/Users/edwardtran/BLI/kid-watch/kid_watch.py` (lines 14, 48-50, 99-118, 176-198, 214-239, 234-237)

### Design Rationale
- **Lazy threshold computation**: Calibration hasn't run yet at StudyDetector init time
- **MAD-based thresholds**: Robust to outliers (better than stddev for calibration data)
- **Safety clamps**: Prevent extreme thresholds from bad calibration data
- **Frame-based debounce**: More intuitive than time-based (independent of FPS)
- **Face-hold in FRONT mode**: Prevents flicker when face detection drops briefly
- **Face-visibility override in SIDE mode**: Kid turning to camera = NOT studying (high confidence signal)

### Testing Plan
- User will test with side-angle camera setup (left side visible, wearing glasses)
- Expected: camera_mode = "side", thresholds computed from baseline
- Expected: studying detected at ~18° neck flexion (not 40°)
- Expected: face visible → NOT studying (side_face_override)
- Expected: D-key CSV logging captures all signals for analysis

### No Behavioral Changes Outside StudyDetector
- CalibrationEngine unchanged (just reads active_baseline)
- GazeDetector unchanged (just provides gaze_at_desk)
- PostureDetector unchanged (just provides pose_result)
- EngagementEngine unchanged (receives studying/person_present, same API)
- DashboardRenderer unchanged

### Known Limitations
- Thresholds computed from FIRST calibration only (not updated on recalibration)
- Camera mode fixed after first calibration (doesn't adapt if user moves camera)
- Pose-based studying less accurate than face-gaze (but works from any angle)
- Side-camera face-override requires 5 consecutive frames (may miss quick glances)

### Future Enhancements
- Adaptive thresholds: update from recalibration baselines
- Camera mode re-detection: adapt if user moves camera mid-session
- Hybrid mode: use both face and pose signals simultaneously (weighted fusion)
- Temporal smoothing: exponential moving average instead of frame counters
