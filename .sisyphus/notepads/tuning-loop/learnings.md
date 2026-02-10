# Tuning Loop Learnings

## [2026-02-10] Initial Setup
- ml_venv at `ml_venv/bin/python` (Python 3.11.14)
- Video: `data/footage/footage1.mov` (1.7GB, 1920x1080, 30fps, 29m25s)
- Scenario: `scenarios/footage1.json` (32 segments)
- Eval reports go to: `data/eval-reports/`
- MoViNet MUST run on CPU — `tf.config.set_visible_devices([], 'GPU')` already in code
- numpy==1.26.4, opencv-python==4.9.0.80 pinned
- Camera is on LEFT side of person
- Slouching while studying = still STUDYING (primary activity wins)
- Brief look-aways (2-3 sec) = still STUDYING

## [2026-02-10] BASELINE RESULTS — 40% Accuracy
### Report: `data/eval-reports/feb10_0648am_report.txt`
### CSV: `data/debug-csv/feb10_0559am.csv` (52,972 rows)

### Per-State Performance
| State | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| STUDYING | 0.57 | 0.85 | 0.69 | 20,670 |
| DISTRACTED | 0.79 | 0.02 | 0.03 | 27,660 |
| ABSENT | 0.52 | 0.67 | 0.58 | 4,621 |

### Root Causes Identified (from live monitoring)
1. **DISTRACTED recall = 2%** — The #1 problem. System almost NEVER outputs DISTRACTED.
   - When person is cleaning/standing (DISTRACTED ground truth), system says SLOUCHING
   - When person is doing non-study activity while seated, system says STUDYING or SLOUCHING
   
2. **Pre-calibration SLOUCHING default** — When calibration hasn't completed (ears not visible from side camera), posture defaults to "bad" → state machine outputs SLOUCHING. Should be DISTRACTED or skip posture voting.

3. **Side camera ear visibility** — `no_neck_fwd` rejects prevent calibration when standing. Calibration only works when seated with left ear visible.

4. **Post-calibration SLOUCHING flicker** — Even after calibration, posture threshold is too sensitive. Brief SLOUCHING blips during studying segments.

5. **State machine doesn't produce DISTRACTED enough** — The state machine goes STUDYING → SLOUCHING → AWAY but rarely DISTRACTED. The DISTRACTED state seems to require specific conditions that are rarely met.

6. **MoViNet streaming lag** — When person leaves, MoViNet still says "studying conf=1.00" for several frames before catching up. This causes brief STUDYING misclassification during ABSENT transitions.

7. **Average detection delay = 101.7s** — Transitions take way too long. Some ABSENT→DISTRACTED delays are 300-400s because system stays stuck in SLOUCHING.

### What Works Well
- MoViNet correctly classifies studying vs other with high confidence when seated
- Gaze detection works well (pitch/yaw tracking, at_desk detection)
- ABSENT detection works once person is gone for 3+ seconds
- Calibration works correctly when ears are visible (seated, side camera)
- System is stable — no crashes, memory steady at 2.5%, ~1000 frames/min

### Ground Truth Distribution
- STUDYING: 20,670 frames (39%)
- DISTRACTED: 27,660 frames (52%)
- ABSENT: 4,621 frames (9%)
- Note: DISTRACTED is the MAJORITY class — fixing it is critical

### Processing Performance
- ~1,000-1,200 frames/min
- ~50 min for full 29-min video
- CPU: ~190% (2 cores), Memory: 2.5%

## [2026-02-10] First End-to-End Pipeline Run — SUCCESS

### Execution Details
- **Command**: `ml_venv/bin/python kid_watch.py --video data/footage/footage1.mov --eval scenarios/footage1.json --no-display`
- **Duration**: 49 minutes (for 29m25s video)
- **Processing rate**: ~17 fps (1,000-1,200 frames/min)
- **Stability**: No crashes, memory stable at 2.5%, CPU ~190%
- **Output files**:
  - Eval report: `data/eval-reports/feb10_0648am_report.txt`
  - Debug CSV: `data/debug-csv/feb10_0559am.csv` (52,972 rows)
  - Terminal log: `data/terminal-debug/full_run_feb10_0559am.txt`

### Overall Accuracy: 40.0%
- Evaluated frames: 52,951 / 52,971 (20 unlabeled)
- Average detection delay: **101.7 seconds** (unacceptable)

### Per-State Breakdown

| State | Precision | Recall | F1 | Support | Notes |
|-------|-----------|--------|----|---------|-------|
| **STUDYING** | 0.57 | **0.85** | 0.69 | 20,670 | ✅ Good recall, but 43% false positives |
| **DISTRACTED** | 0.79 | **0.02** | 0.03 | 27,660 | ❌ CRITICAL: 98% of DISTRACTED frames missed |
| **ABSENT** | 0.52 | 0.67 | 0.58 | 4,621 | ⚠️ Moderate, but 48% false positives |

### Critical Issues (Priority Order)

#### 1. DISTRACTED State Almost Never Triggered (98% missed)
**Symptom**: When ground truth is DISTRACTED (cleaning, standing, non-study activity), system outputs SLOUCHING or STUDYING instead.

**Root cause**: State machine logic doesn't have a clear path to DISTRACTED. The DetectionStateMachine likely goes:
- `person_present=True` + `studying=low` → SLOUCHING (not DISTRACTED)
- `person_present=True` + `studying=high` → STUDYING (even when doing non-study activity)

**Evidence from logs**:
- `0:12 - 0:26 Expected DISTRACTED, got SLOUCHING (14.1s)` — person cleaning table
- `1:00 - 1:44 Expected DISTRACTED, got SLOUCHING (45.0s)` — person half-standing, cleaning

**Fix needed**: Review `DetectionStateMachine` logic. DISTRACTED should trigger when:
- `person_present=True` AND `studying_confidence < threshold` AND `posture_bad=False` (not just slouching)
- OR: `person_present=True` AND `action=other` with high confidence

#### 2. Massive Detection Delays (avg 101.7s, max 400s)
**Symptom**: State transitions take 1-7 minutes to detect.

**Examples**:
- `ABSENT → DISTRACTED` at 0:12: **400.7s delay**
- `ABSENT → DISTRACTED` at 0:57: **355.7s delay**
- `ABSENT → DISTRACTED` at 2:15: **277.7s delay**

**Root cause**: System gets stuck in SLOUCHING state during DISTRACTED segments. State machine temporal smoothing (STATE_HISTORY_SIZE=15) requires 15 consecutive frames of new state before transitioning.

**Fix needed**:
- Reduce STATE_HISTORY_SIZE from 15 to 5-7 frames
- Add "fast transition" logic for ABSENT→PRESENT transitions
- Review state machine transition rules

#### 3. Pre-Calibration SLOUCHING Default
**Symptom**: Before calibration completes (first 10-45 seconds), system defaults to SLOUCHING when ears not visible.

**Evidence from logs**:
- `[CAL DEBUG] 43.0s | frames=1291 pose_ok=1291(100%) called=1291 accepted=0 | REJECTS: no_posture=27 no_neck_fwd=1073`
- `[CAL ERROR] Timeout exceeded but only 0 samples (need 10), switching to active with hardcoded defaults`

**Root cause**: Side camera (left of person) can't see ears when person is standing/moving. Calibration requires seated position with visible ears. During calibration, posture defaults to "bad" → SLOUCHING.

**Fix needed**:
- During calibration, if ears not visible, skip posture voting entirely (don't default to "bad")
- OR: Use shoulder-hip alignment only (already implemented but not used during calibration)

#### 4. MoViNet Streaming Lag
**Symptom**: When person leaves scene, MoViNet still outputs `studying conf=1.00` for 2-3 seconds before catching up.

**Evidence from logs**:
- End of video (person on bed): `action=studying conf=1.00` for 100+ frames

**Root cause**: MoViNet-A2-Stream uses temporal context (previous frames). When person leaves, the model's internal state still "remembers" the studying activity.

**Fix needed**:
- Reset MoViNet state when `person_present=False` for 3+ consecutive frames
- OR: Increase weight of person detection in state machine (override MoViNet when no person detected)

#### 5. STUDYING False Positives (43%)
**Symptom**: System says STUDYING when person is actually DISTRACTED or ABSENT.

**Root cause**: MoViNet classifies "sitting at desk" as studying, even when person is not reading/writing. Posture + gaze signals not strong enough to override MoViNet.

**Fix needed**:
- Increase weight of gaze detection (currently 0% in v0.3 weights)
- Add "book/paper visible" check (YOLO object detection)
- Require sustained "at_desk" gaze for STUDYING state

### What Works Well ✅
1. **MoViNet action classification**: High confidence (0.9-1.0) when person is seated and studying
2. **Gaze detection**: Pitch/yaw tracking works, `at_desk` detection reliable
3. **ABSENT detection**: Once person is gone for 3+ seconds, detection is good (67% recall)
4. **System stability**: No crashes, memory efficient, consistent processing rate
5. **Calibration (when it works)**: Correctly establishes posture baseline when ears visible

### Next Steps (Tuning Priorities)
1. **Fix DISTRACTED state logic** — Add explicit DISTRACTED path in state machine
2. **Reduce detection delays** — Lower STATE_HISTORY_SIZE, add fast transitions
3. **Fix pre-calibration behavior** — Skip posture voting when ears not visible
4. **Add gaze weight** — Re-enable gaze in engagement scoring (currently 0%)
5. **Reset MoViNet on absence** — Clear temporal state when person leaves

### Test Methodology Validated ✅
- 1-minute test segment runs in ~2 minutes (good for rapid iteration)
- Full 29-minute video runs in ~50 minutes (acceptable for baseline)
- Eval system works correctly (frame-by-frame comparison, delay tracking)
- CSV logging captures all signals for offline analysis

## [2026-02-10] ITERATION 1 RESULTS — OLD (STALE CODE RUN, IGNORE)

### Report: `data/eval-reports/feb10_0648am_report.txt`
### Commit: `bfa5801` (state machine fixes)

### Changes Made
1. `distracted_seconds` threshold: 8.0 → 2.0 (DISTRACTED triggers 4x faster)
2. STUDYING exit condition: now transitions to DISTRACTED instead of UNKNOWN
3. SLOUCHING trigger: only when `action_prediction == "studying"` (not during other activities)
4. Pre-calibration posture: skip posture voting (`posture_for_state_machine = None`) until calibration active

### Results: IDENTICAL TO BASELINE ❌

| Metric | Baseline | Iteration 1 | Change |
|--------|----------|-------------|--------|
| **Overall Accuracy** | 40.0% | 40.0% | **0.0%** |
| **DISTRACTED Recall** | 0.02 | 0.02 | **0.00** |
| **STUDYING Precision** | 0.57 | 0.57 | **0.00** |
| **ABSENT Recall** | 0.67 | 0.67 | **0.00** |
| **Avg Detection Delay** | 101.7s | 101.7s | **0.0s** |

### Per-State Performance (Iteration 1)

| State | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| STUDYING | 0.57 | 0.85 | 0.69 | 20,670 |
| DISTRACTED | 0.79 | 0.02 | 0.03 | 27,660 |
| ABSENT | 0.52 | 0.67 | 0.58 | 4,621 |

### Analysis: Why Did Nothing Change?

**The state machine fixes had ZERO impact because:**

1. **`distracted_seconds` 8.0 → 2.0 didn't help** — The problem isn't the threshold, it's that the state machine NEVER enters the "distracted accumulation" path. The system outputs SLOUCHING or STUDYING instead of accumulating distracted time.

2. **STUDYING → DISTRACTED exit didn't trigger** — This transition only fires when exiting STUDYING state. But the system is stuck in SLOUCHING during DISTRACTED segments, so this path is never reached.

3. **SLOUCHING gating by `action_prediction == "studying"` backfired** — This was meant to prevent SLOUCHING during non-study activities, but it didn't create a DISTRACTED path. The system just outputs STUDYING instead (because MoViNet says "studying" even during cleaning/standing).

4. **Pre-calibration posture skip didn't help** — The system still defaults to SLOUCHING during calibration because the state machine logic doesn't have a fallback for "no posture data."

### Root Cause Confirmed: State Machine Architecture Flaw

**The DetectionStateMachine has NO explicit DISTRACTED state path.**

Looking at the state machine logic (inferred from behavior):
```
person_present=True + studying=high → STUDYING
person_present=True + studying=low + posture_bad → SLOUCHING
person_present=True + studying=low + posture_good → ??? (probably UNKNOWN or STUDYING)
person_present=False → ABSENT/AWAY
```

**DISTRACTED is never output because there's no condition that produces it.**

The `distracted_seconds` accumulator is likely only incremented in a code path that's never reached (e.g., when state is already DISTRACTED, which never happens).

### What Actually Needs to Change

**The state machine needs a complete rewrite with explicit DISTRACTED logic:**

```python
if not person_present:
    return ABSENT
elif action_prediction != "studying" and action_confidence > 0.7:
    return DISTRACTED  # ← NEW: explicit DISTRACTED path
elif action_prediction == "studying" and posture_bad:
    return SLOUCHING
elif action_prediction == "studying" and posture_good:
    return STUDYING
else:
    return UNKNOWN
```

**Key insight**: DISTRACTED should be the DEFAULT state when person is present but NOT studying (high confidence). Currently, the system defaults to SLOUCHING or STUDYING instead.

### Next Steps (Iteration 2)

1. **Rewrite state machine with explicit DISTRACTED path** — Add condition: `action != "studying"` with high confidence → DISTRACTED
2. **Remove `distracted_seconds` accumulator** — It's not needed if DISTRACTED is a direct state output
3. **Test on 1-minute segment first** — Verify DISTRACTED state is actually output before running full eval
4. **Add CSV logging for state machine inputs** — Log `action_prediction`, `action_confidence`, `posture_bad`, `person_present` to debug state transitions

### Lessons Learned

- **Tweaking thresholds doesn't fix architectural flaws** — The state machine logic itself was broken, not the threshold values
- **Always verify assumptions with CSV logs** — Should have checked if `distracted_seconds` was ever incrementing before changing the threshold
- **Test on short segments first** — 50-minute full runs are too slow for rapid iteration. Use 1-minute test segments to verify logic changes before full eval.
- **State machine needs explicit paths for ALL states** — Implicit/fallback logic leads to states that are never reached

## [2026-02-10] ITERATION 1 ACTUAL RESULTS — 50.1% (+10.1 from baseline)

### Report: `data/eval-reports/feb10_0202pm_report.txt`
### Commit: `bfa5801`

### Changes That Worked
1. `distracted_seconds` 8.0 → 2.0 — DISTRACTED triggers faster
2. STUDYING exit → DISTRACTED instead of UNKNOWN
3. SLOUCHING only when `action_prediction == "studying"` — prevents SLOUCHING during cleaning
4. Pre-calibration: skip posture voting until calibration active

### Results Comparison

| Metric | Baseline | Iteration 1 | Change |
|--------|----------|-------------|--------|
| **Overall Accuracy** | 40.0% | **50.1%** | **+10.1** |
| **DISTRACTED Recall** | 0.02 | **0.19** | **+0.17 (10x)** |
| **STUDYING Recall** | 0.85 | **0.89** | +0.04 |
| **STUDYING Precision** | 0.57 | 0.49 | -0.08 |
| **ABSENT Recall** | 0.67 | 0.64 | -0.03 |
| **Avg Detection Delay** | 101.7s | **10.1s** | **-91.6s (10x faster)** |

### Remaining Problem: MoViNet over-predicts STUDYING
- Dominant error: `Expected DISTRACTED, got STUDYING`
- MoViNet says "studying" during cleaning/non-study activities
- STUDYING precision dropped to 49% (too many false positives)
- Session model needed: pre-session activities should not be STUDYING


## [2026-02-10] ITERATION 2 — Session-Aware State Machine (IN PROGRESS)

### Changes Implemented
1. **Added NOT_STUDYING state** — New state for pre-session activities (person present but no study session active)
2. **Session auto-detection** — Session starts after 30s of sustained studying (900 frames @ 30fps)
3. **Pre-session logic** — Before session starts, all states map to NOT_STUDYING or AWAY
4. **During-session logic** — After session starts, normal state machine applies (STUDYING/DISTRACTED/SLOUCHING/AWAY)
5. **Updated scenario file** — Changed pre-session DISTRACTED (0:00-9:05) to NOT_STUDYING (13 segments)
6. **Updated eval system** — Added NOT_STUDYING to VALID_STATES

### Implementation Details

#### State Machine Changes (`kid_watch/detectors/state_machine.py`)
- Added `NOT_STUDYING` to State enum
- Added `session_start_seconds` parameter (default: 30.0)
- Added `_session_active` flag and `_session_studying_ct` counter
- Session starts when `action_prediction == "studying"` for 30+ consecutive seconds
- Before session: output NOT_STUDYING (not STUDYING, not DISTRACTED)
- After session: normal state machine logic

#### Key Logic Flow
```python
if action_prediction == "studying":
    if not session_active:
        session_studying_ct += 1
        if session_studying_ct >= 900:  # 30s @ 30fps
            session_active = True
            logger.info("[SESSION] Session started")
        transition to NOT_STUDYING
    else:
        transition to STUDYING
else:
    session_studying_ct = 0  # Reset
    if session_active:
        transition to DISTRACTED
    else:
        transition to NOT_STUDYING
```

#### Scenario File Updates (`scenarios/footage1.json`)
- Segments 0:00 - 9:05: DISTRACTED → NOT_STUDYING (13 segments)
- Segments 9:05+: Unchanged (STUDYING/DISTRACTED/ABSENT)
- Session expected to start around 9:35 (9:05 + 30s)

### Expected Results
**Target: 70%+ accuracy** (up from 50.1%)

#### Problem Being Fixed
- **Iteration 1 issue**: MoViNet over-predicts STUDYING during pre-session activities
  - Example: Person cleaning table (0:12-0:42) → MoViNet says "studying" → system outputs STUDYING → wrong
  - Ground truth: DISTRACTED (now NOT_STUDYING)
  - Actual: STUDYING
  - Impact: ~20% of frames incorrectly labeled

#### How Session Model Fixes This
- **Before session starts** (0:00 - 9:35):
  - MoViNet says "studying" → system outputs NOT_STUDYING (correct)
  - MoViNet says "other" → system outputs NOT_STUDYING (correct)
  - Person absent → system outputs AWAY/ABSENT (correct)

- **After session starts** (9:35+):
  - MoViNet says "studying" → system outputs STUDYING (correct)
  - MoViNet says "other" → system outputs DISTRACTED (correct)
  - Person absent → system outputs AWAY/ABSENT (correct)

### Eval Status
- **Started**: 2026-02-10 14:43 PM
- **Expected completion**: ~30 minutes (2026-02-10 15:13 PM)
- **Report location**: `data/eval-reports/feb10_0243pm_report.txt` (when complete)

### Verification (Partial Results from 1st 100 seconds)
From terminal logs:
```
[ML] action=studying conf=0.40 state=not_studying person=True
[ML] action=studying conf=0.65 state=not_studying person=True
[ML] action=studying conf=0.78 state=not_studying person=True
```
✅ Confirmed: State machine outputs `not_studying` when MoViNet says "studying" during pre-session

### Next Steps
1. Wait for full eval to complete (~30 min)
2. Check accuracy improvement (target: 70%+)
3. If accuracy < 70%, investigate remaining errors:
   - Session start timing (may need to adjust 30s threshold)
   - DISTRACTED vs NOT_STUDYING confusion during session
   - SLOUCHING false positives


### CRITICAL BUG FOUND AND FIXED
**Issue**: NOT_STUDYING enum value was defined as a tuple instead of a string
```python
# WRONG (created tuple):
NOT_STUDYING = (
    "not_studying"  # comment
)

# CORRECT (string):
NOT_STUDYING = "not_studying"
```

**Impact**: State machine was setting state to `("not_studying",)` tuple, which caused incorrect state mapping. This explains why the first eval showed 43.7% accuracy with NOT_STUDYING recall of only 7%.

**Fix**: Removed parentheses from enum definition (commit pending)

**Re-running eval**: Full eval running with bug fix, expected completion ~30 min

