# Decisions — v0.3 MoViNet ML Pipeline

## [2026-02-08] Architecture Decisions
1. Python 3.11 + TF 2.17 + tensorflow-metal 1.2.0 (NOT 3.12)
2. Fine-tune MoViNet-A2-Stream directly (base→stream conversion impossible)
3. 3 MoViNet classes: studying, sleeping, other
4. Drop gaze entirely, reweight engagement formula
5. YOLOv8n-pose replaces MediaPipe Pose
6. Single person assumption
7. Feature flag for old/new detector toggle

## [2026-02-08] Implementation Decisions (Final)

### Data Pipeline
- **Kinetics-700 selective download**: 1,000 URLs per class (expect 50% success)
- **Class mapping**: reading_book + reading_newspaper + writing → studying; sleeping + yawning → sleeping; random others → other
- **Preprocessing**: 172×172, 5 FPS, 50 frames, float32 [0,1], stratified 80/10/10 split
- **Augmentation**: Basic only (horizontal flip, brightness ±0.1, contrast ±0.1)

### Model Architecture
- **MoViNet-A2-Stream**: Fine-tune streaming variant directly (NOT base model)
- **Training strategy**: Stage 1 (head-only, 5 epochs) → Stage 2 (fine-tune top 20%, 15 epochs)
- **Classes**: 3 outputs (studying, sleeping, other) — "distracted" is temporal logic, not model class
- **Confidence threshold**: 0.4 (if max softmax < 0.4, return "other")

### Inference & Performance
- **Skip-frame strategy**: Run MoViNet every 5th frame (82.7ms amortized, 12.1 FPS effective)
- **State machine debouncing**: studying(3 frames enter, 5 exit), sleeping(3), distracted(8s), away(3s), slouch(30 frames)
- **Engagement scoring**: posture(0.30) + studying_confidence(0.40) + no_phone(0.30) — gaze removed entirely

### Integration
- **Feature flag**: `USE_ML_DETECTOR` toggles between new (ML) and old (MediaPipe) pipelines
- **MoViNet state reset**: On camera disconnect or person absent >5s
- **Full-frame processing**: No person cropping for v0.3 (may revisit if accuracy poor)
- **Single person assumption**: If >1 person detected, use largest bounding box

### Documentation & Versioning
- **Model versioning**: `movinet_a2_stream_v{major}.{minor}_{date}_{dataset_hash}`
- **Data manifest**: SHA256 hashes for all clips (integrity verification)
- **README**: Practical training instructions, architecture overview, known limitations


## [2026-02-09] 3-Level Reset Strategy for MoViNet Streaming State

### Problem
The old 10-second periodic reset was too aggressive:
- MoViNet correctly predicted "studying" at 0.79 confidence
- 10s reset fired → confidence jumped to "other" at 0.96 (wrong!)
- Took 30 seconds to recover because EMA was also wiped
- User was marked "NOT STUDYING" for 30s while actually studying

### Solution: 3-Level Reset System

**Level 1: Conditional Reset (raw disagrees with EMA for 2s)**
- Tracks raw (pre-EMA) predictions vs EMA predictions
- If they disagree for 2 continuous seconds → reset streaming state
- **KEEPS EMA** — EMA bridges across the reset
- Catches genuine behavior changes without destroying correct predictions

**Level 2: Safety Reset (every 30s)**
- Periodic reset to prevent slow drift to 1.00 confidence
- Increased from 10s to 30s to reduce disruption
- **KEEPS EMA** — EMA bridges across the reset
- Rare enough to not be disruptive

**Level 3: Hard Reset (person gone 2s)**
- Called via `reset_state()` when person disappears
- **WIPES EVERYTHING** including EMA
- Only reset that destroys EMA

### Implementation Details

**`_init_states()` no longer resets EMA**
- Old: `_init_states()` set `self._ema_probs = None`
- New: `_init_states()` only resets TensorFlow streaming states
- EMA reset is now explicit only in `reset_state()` (Level 3)

**New state variables**
- `_disagreement_start`: Timestamp when raw started disagreeing with EMA
- `_disagreement_threshold`: 2.0 seconds of disagreement before reset
- `_safety_reset_interval`: 30.0 seconds (was `_state_reset_interval = 10.0`)

**Removed**
- `_saturation_start`, `_saturation_threshold`, `_saturation_timeout` (saturation watchdog)
- Saturation watchdog was superseded by conditional reset (smarter)

### Expected Behavior
- User studying → MoViNet predicts "studying" at 0.79
- Raw predictions may fluctuate but EMA stays stable
- If raw disagrees with EMA for 2s → conditional reset fires
- Streaming state resets but EMA keeps "studying" at 0.79
- No jarring flip to "other" — smooth recovery

### Constants
| Constant | Value | Purpose |
|----------|-------|---------|
| `_safety_reset_interval` | 30.0s | Level 2 safety reset |
| `_disagreement_threshold` | 2.0s | Level 1 conditional reset |
| `_ema_decay` | 0.9 | EMA smoothing (unchanged) |
| `confidence_threshold` | 0.4 | Classification threshold (unchanged) |

### Logging
- Level 1: `[MOVINET] Conditional reset: raw=X disagrees with EMA=Y for Z.Zs`
- Level 2: `[MOVINET] Safety reset (Z.Zs elapsed)`
- Level 3: `[MOVINET] Hard reset (person disappeared)`
- Debug: `[MOVINET] raw=X(0.XX) ema=Y(0.YY) disagreeing=YES/no`


## [2026-02-09] Calibration Position Change Detection & Recalibration Fixes

### Problem
Two interrelated issues in `kid_watch/calibration.py`:

**Problem A: Slouching/sleeping triggers false position changes**
- User slouches/sleeps → shoulder midpoint moves ~100+ pixels downward
- `check_position_change()` sees large movement → triggers recalibration
- But this is NOT a position change — it's a posture change
- Evidence from live test: forward_lean went from 4° → 72-79° during sleep

**Problem B: Recalibration starts in bad posture and fails**
- Recalibration triggered while user is still slouched/sleeping
- `add_sample()` immediately starts collecting samples
- All samples rejected because forward_lean > 60° (bad posture)
- After 2.0s of bad posture → resets to "waiting" state
- Evidence: `fwd_lean=36 out of 77 frames` rejected during recalibration

### Solution

**Fix A: Slouch Gate in Position Change Detection**
- Added `SLOUCH_GATE_THRESHOLD = 12.0` constant (degrees above baseline)
- Modified `check_position_change()` to accept optional `forward_lean` parameter
- If `forward_lean > baseline + 12°` → ignore position change, reset counter
- Rationale: Baseline forward_lean is ~4°, slouch is 60-80°, gate at 16° catches all slouches
- Hip-first tracking also added (optional `hip_centroid` parameter) but not wired up yet
  - Hip center is more stable during slouch than shoulders
  - Will be wired up when `kid_watch.py` is modified in future task

**Fix B: Neutral Posture Settle Before Sampling**
- Added `_neutral_settle_start` and `_neutral_settle_required = 1.0s` instance variables
- Modified `add_sample()` to check for neutral posture (forward_lean < 15°) BEFORE collecting samples
- If not neutral → reset settle timer and reject sample
- If neutral for < 1.0s → reject sample (still settling)
- If neutral for >= 1.0s → proceed with normal sample collection
- Reset `_neutral_settle_start` in `_start_calibrating()` and `trigger_recalibration()`

**Fix C: Increased Post-Calibration Cooldown**
- Changed `CALIBRATION_COOLDOWN_SECONDS` from 5.0 → 10.0
- Gives user more time to settle after calibration before position tracking resumes

### Implementation Details

**Modified constants:**
```python
CALIBRATION_COOLDOWN_SECONDS = 10.0  # was 5.0
SLOUCH_GATE_THRESHOLD = 12.0  # new
```

**Modified `check_position_change()` signature:**
```python
def check_position_change(self, pose_centroid, hip_centroid=None, forward_lean=None):
```
- Backward compatible (optional parameters)
- Slouch gate logic runs before position distance computation
- Logs tracking mode ("hip" or "shoulder") in `[CAL POS]` output

**Modified `add_sample()` logic:**
- Neutral posture check runs AFTER basic validation (posture_metrics exists, neck/forward_lean present)
- Settle timer starts when forward_lean < 15° first detected
- Samples rejected until 1.0s of continuous neutral posture

**New instance variables:**
- `_neutral_settle_start`: Timestamp when neutral posture first detected (None if not neutral)
- `_neutral_settle_required`: 1.0 seconds of neutral before sampling

### Expected Behavior

**Slouch scenario:**
1. User is studying (forward_lean ~4°)
2. User slouches to sleep (forward_lean → 72°)
3. Shoulders move 100+ pixels downward
4. `check_position_change()` receives forward_lean=72°
5. Slouch gate: 72° > 4° + 12° → position change IGNORED
6. Counter reset to 0, no recalibration triggered

**Recalibration scenario:**
1. User moves to new position (genuine position change)
2. Recalibration triggered
3. User still adjusting posture (forward_lean = 25°)
4. `add_sample()` rejects samples (not neutral yet)
5. User settles into neutral posture (forward_lean = 8°)
6. Settle timer starts
7. After 1.0s of continuous neutral → samples start collecting
8. Calibration completes successfully

### Logging Updates

**`[CAL POS]` log now shows:**
```
[CAL POS] tracking=hip x_change=0.1138 y_change=0.0791 consecutive=3/15
[CAL POS] tracking=shoulder x_change=0.1215 y_change=0.0966 consecutive=5/15
```
- Tracking mode indicates whether hip or shoulder centroid is being used
- No "(slouch-gated)" suffix added (kept log simple)

### Future Work

**Hip-first tracking wiring:**
- Currently `kid_watch.py` passes only `pose_centroid` (shoulder midpoint)
- Need to extract hip keypoints (COCO indices 11, 12) and pass `hip_centroid`
- Hip center = midpoint of left_hip and right_hip in pixel coordinates
- Will be done in separate task when modifying `kid_watch.py`

**Known limitations:**
- Laptop cameras with tight angles may not see hips → falls back to shoulders
- Viettel ceiling cameras will always see hips (better stability)
- Slouch gate threshold (12°) may need tuning based on real-world data

### Constants Reference

| Constant | Value | Purpose |
|----------|-------|---------|
| `CALIBRATION_COOLDOWN_SECONDS` | 10.0s | Post-calibration cooldown (was 5.0s) |
| `SLOUCH_GATE_THRESHOLD` | 12.0° | Forward lean above baseline to gate position changes |
| `_neutral_settle_required` | 1.0s | Neutral posture duration before sampling |
| `GOOD_POSTURE_LEAN_THRESHOLD` | 15.0° | Neutral posture threshold (unchanged) |
| `POSITION_CHANGE_CONSECUTIVE_FRAMES` | 15 | Frames required for position change (unchanged) |

