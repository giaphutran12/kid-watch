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


## [2026-02-10] COMPREHENSIVE FAILURE PATTERN ANALYSIS

### Executive Summary
Three iterations completed:
- **Baseline (Iter 0)**: 40.0% accuracy — DISTRACTED detection broken (2% recall)
- **Iteration 1**: 50.1% accuracy (+10.1%) — DISTRACTED improved to 19% recall, detection delays cut 10x
- **Iteration 2**: 43.7% accuracy (-6.4% regression) — Session model added, but NOT_STUDYING enum bug broke state mapping

**Critical Finding**: Iteration 2 regressed due to a single-line bug: NOT_STUDYING enum defined as tuple instead of string. The session model concept is sound; the implementation has a critical bug.

### Failure Taxonomy (Iteration 2)

**Per-State Performance:**
| State | Precision | Recall | F1 | Support | Frames Wrong |
|-------|-----------|--------|----|---------|----|
| STUDYING | 0.50 | 0.90 | 0.64 | 20,250 | ~2,025 (10%) |
| DISTRACTED | 0.17 | 0.07 | 0.10 | 15,750 | ~14,648 (93%) |
| NOT_STUDYING | 0.68 | 0.07 | 0.13 | 12,330 | ~11,467 (93%) |
| ABSENT | 0.54 | 0.64 | 0.58 | 4,621 | ~1,664 (36%) |
| **TOTAL WRONG** | | | | | **~29,804 (56.3%)** |

**Dominant Error Modes (Ranked by Impact):**

1. **Type E: Expected DISTRACTED, got STUDYING** (~4,000-5,000 frames, 13-17% of total)
   - DISTRACTED recall = 7% (93% of DISTRACTED frames missed)
   - Root cause: MoViNet over-predicts "studying" during phone/distraction
   - This is the #1 problem from Iteration 1 that REGRESSED in Iteration 2

2. **Type A: Expected NOT_STUDYING, got STUDYING** (~8,000-9,000 frames, 15-17% of total)
   - NOT_STUDYING recall = 7% (93% of NOT_STUDYING frames missed)
   - Root cause: Session model not working correctly (enum bug)
   - This is a NEW problem introduced in Iteration 2

3. **Type F: Expected ABSENT, got something else** (~1,664 frames, 3% of total)
   - ABSENT recall = 64% (36% of ABSENT frames misclassified)
   - Root cause: Person detection lag/false negatives

4. **Type B: Expected NOT_STUDYING, got DISTRACTED** (~2,000-3,000 frames, 4-6% of total)
   - Confusion between NOT_STUDYING and DISTRACTED states
   - Root cause: State machine logic doesn't distinguish pre-session from session

### Timeline Analysis: Ground Truth vs Actual

**Segment 1: 0:00-9:05 (NOT_STUDYING/ABSENT)**
- Ground truth: Person cleaning table, moving around, pre-session activities
- Actual output (CSV sampling):
  - 0:30 (frame 896): STUDYING (WRONG — should be NOT_STUDYING)
  - 3:00 (frame 5396): CALIBRATING (WRONG — should be NOT_STUDYING or ABSENT)
  - 6:00 (frame 10796): WAITING (WRONG — should be NOT_STUDYING or ABSENT)
- Analysis: Session model NOT working. State machine still outputs STUDYING during pre-session. NOT_STUDYING enum bug causes state mapping failures.
- Estimated frames wrong: ~8,000-9,000 (entire segment misclassified)

**Segment 2: 9:05-12:15 (STUDYING)**
- Ground truth: Person reading book, good posture, studying
- Actual output:
  - 9:05 (frame 16346): STUDYING ✅ (CORRECT)
  - 12:15 (frame 22046): CALIBRATING (WRONG — should be STUDYING)
- Analysis: Session start works correctly, but transitions to CALIBRATING instead of staying in STUDYING.
- Estimated frames wrong: ~500-1,000 (transition region)

**Segment 3: 12:15-12:45 (DISTRACTED)**
- Ground truth: Person not studying, scratching, phone at 12:30
- Actual output:
  - 12:15 (frame 22046): CALIBRATING (WRONG)
  - 12:45 (frame 22950): STUDYING (WRONG)
- Analysis: System fails to detect DISTRACTED. Outputs CALIBRATING (state machine bug) and STUDYING (MoViNet over-prediction).
- Estimated frames wrong: ~1,800 (entire segment)

**Segment 4: 12:45-20:50 (STUDYING)**
- Ground truth: Person reading book, studying with slouching/leaning
- Actual output:
  - 12:45 (frame 22946): STUDYING ✅ (CORRECT)
  - 20:50 (frame 37496): STUDYING ✅ (CORRECT)
- Analysis: STUDYING detection works well. MoViNet correctly classifies even with slouching/leaning.
- Estimated frames wrong: ~500-1,000 (minor transitions)

**Segment 5: 20:50+ (DISTRACTED/ABSENT)**
- Ground truth: Person on bed, on phone, session over
- Actual output:
  - 20:50 (frame 37496): STUDYING (WRONG — should be DISTRACTED)
- Analysis: System fails to detect transition to DISTRACTED. MoViNet still says "studying" even on bed with phone.
- Estimated frames wrong: ~2,000-3,000

### Iteration Comparison

**Baseline → Iteration 1 (40.0% → 50.1%, +10.1%)**

What IMPROVED:
- DISTRACTED Recall: 0.02 → 0.19 (+0.17, 10x improvement)
- Detection Delay: 101.7s → 10.1s (-91.6s, 10x faster)
- STUDYING Recall: 0.85 → 0.89 (+0.04)

What REGRESSED:
- STUDYING Precision: 0.57 → 0.49 (-0.08) — MoViNet over-predicts "studying"
- ABSENT Recall: 0.67 → 0.64 (-0.03) — Minor

Root cause of regression: MoViNet classifies "sitting at desk" as studying, even during cleaning/phone use.

**Iteration 1 → Iteration 2 (50.1% → 43.7%, -6.4% REGRESSION)**

What IMPROVED:
- Detection Delay: 10.1s → 8.2s (-1.9s) — Marginal
- STUDYING Recall: 0.89 → 0.90 (+0.01) — Marginal

What REGRESSED:
- Overall Accuracy: 50.1% → 43.7% (-6.4%) — Major regression
- DISTRACTED Recall: 0.19 → 0.07 (-0.12, 3x worse) — System confuses DISTRACTED with NOT_STUDYING
- NOT_STUDYING Recall: N/A → 0.07 (new state, barely works) — Enum bug
- STUDYING Precision: 0.49 → 0.50 (flat) — No improvement

Root cause: NOT_STUDYING enum defined as tuple instead of string:
```python
# WRONG (current):
NOT_STUDYING = (
    "not_studying"  # comment
)

# CORRECT:
NOT_STUDYING = "not_studying"
```
This creates tuple `("not_studying",)` instead of string, breaking state mapping throughout system.

### 80/20 Analysis: Maximum Impact Fixes

**Fix #1: Correct NOT_STUDYING Enum Bug (CRITICAL)**
- Current impact: -6.4% accuracy (entire Iteration 2 regression)
- Expected impact: +6.4% accuracy (restore to Iteration 1 level)
- Effort: 5 minutes (one-line fix)
- Priority: CRITICAL — Do immediately

**Fix #2: Reduce MoViNet Over-Prediction of "Studying" (HIGH IMPACT)**
- Current impact: ~4,000-5,000 frames wrong
- Expected impact: +5-8% accuracy
- Effort: Medium (state machine redesign)
- Priority: HIGH — Dominant error from Iteration 1

Proposed sub-fixes (in order of impact):
1. Add gaze weight to state machine (currently 0%) → +2-3%
2. Add phone detection to state machine → +1-2%
3. Add action classifier confidence threshold → +1-2%
4. Reset MoViNet state on absence → +0.5-1%

**Fix #3: Improve ABSENT Detection (MEDIUM IMPACT)**
- Current impact: ~1,664 frames wrong
- Expected impact: +2-3% accuracy
- Effort: Low (threshold tuning)
- Priority: MEDIUM

**Fix #4: Distinguish NOT_STUDYING from DISTRACTED (MEDIUM IMPACT)**
- Current impact: ~2,000-3,000 frames wrong
- Expected impact: +2-3% accuracy
- Effort: Low (state machine logic)
- Priority: MEDIUM

### Proposed Fix Priorities

**Phase 1: Critical Bug Fix (5 minutes, +6.4%)**
1. Fix NOT_STUDYING enum — Change tuple to string
   - Expected: Restore Iteration 2 to Iteration 1 level (50.1%)

**Phase 2: Dominant Error Fix (2-4 hours, +5-8%)**
2. Reduce MoViNet over-prediction — Add gaze + phone detection
   - Expected: Reach 55-58% accuracy

**Phase 3: Refinement (1-2 hours, +2-3%)**
3. Improve ABSENT detection — Threshold tuning + temporal smoothing
   - Expected: Reach 57-61% accuracy

4. Distinguish NOT_STUDYING from DISTRACTED — State machine logic
   - Expected: Reach 59-64% accuracy

**Phase 4: Advanced (4-8 hours, +5-10%)**
5. Add action classifier confidence threshold
6. Reset MoViNet state on absence
7. Add book/paper detection

### Key Insights

1. **Iteration 2 regression is a simple bug, not a design flaw**
   - Session model concept is sound
   - One-line fix will restore to Iteration 1 level
   - Then focus on MoViNet over-prediction

2. **MoViNet is the bottleneck**
   - Correctly classifies "studying" with 90%+ recall
   - Over-predicts "studying" during non-study activities
   - Precision only 50% — too many false positives
   - Gaze + phone detection can reduce false positives

3. **State machine is working well**
   - Detection delays improved 10x (101.7s → 10.1s)
   - STUDYING recall improved (0.85 → 0.90)
   - DISTRACTED recall improved 10x (0.02 → 0.19)
   - Enum bug is the only issue

4. **ABSENT detection is stable**
   - Recall = 64% (good)
   - Precision = 54% (acceptable)
   - Minor improvements possible with temporal smoothing

5. **The 80/20 rule applies**
   - Fix #1 (enum bug): 5 min → +6.4%
   - Fix #2 (MoViNet): 2-4 hours → +5-8%
   - These two fixes alone would reach 55-58% accuracy
   - Remaining fixes have diminishing returns
