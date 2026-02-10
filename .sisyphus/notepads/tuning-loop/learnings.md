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

